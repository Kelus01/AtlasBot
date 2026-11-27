import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import disnake
from disnake.ext import commands


GUILD_ID = 1572541450489430036
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATABASE_PATH = DATA_DIR / "moderation.sqlite3"
MAX_REASON_LENGTH = 500
MAX_TIMEOUT_MINUTES = 28 * 24 * 60

logger = logging.getLogger(__name__)


class Admin(commands.Cog):
    def __init__(self, bot: commands.InteractionBot) -> None:
        self.bot = bot
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DATABASE_PATH) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    revoked_by INTEGER,
                    revoked_at TEXT
                )
                """
            )

    @staticmethod
    def _reason_error(reason: str) -> str | None:
        if not reason.strip():
            return "Вкажіть причину."
        if len(reason.strip()) > MAX_REASON_LENGTH:
            return f"Причина не може бути довшою за {MAX_REASON_LENGTH} символів."
        return None

    @staticmethod
    def _target_error(
        inter: disnake.ApplicationCommandInteraction,
        target: disnake.Member,
        permission: str,
    ) -> str | None:
        guild = inter.guild
        if guild is None:
            return "Команду можна використовувати лише на сервері."
        if not getattr(inter.author.guild_permissions, permission):
            return "У вас немає потрібного дозволу для цієї дії."
        if target.id == guild.owner_id:
            return "Не можна застосувати цю дію до власника сервера."
        if target.id == inter.author.id:
            return "Не можна застосувати цю дію до себе."
        if (
            inter.author.id != guild.owner_id
            and not inter.author.guild_permissions.administrator
            and target.top_role >= inter.author.top_role
        ):
            return "Не можна модерувати учасника з рівною або вищою роллю."

        bot_member = guild.me
        if bot_member is None:
            return "Не вдалося перевірити ролі бота на сервері."
        if target.top_role >= bot_member.top_role:
            return "Перемістіть роль бота вище за роль цього учасника."
        return None

    @staticmethod
    async def _run_action(
        inter: disnake.ApplicationCommandInteraction,
        action: Callable[[], Awaitable[object]],
        success_message: str,
        action_name: str,
    ) -> None:
        await inter.response.defer(ephemeral=True)
        try:
            await action()
        except disnake.Forbidden:
            logger.exception(
                "Discord заборонив дію модерації %s (moderator_id=%s)",
                action_name,
                inter.author.id,
            )
            await inter.edit_original_response(
                "Discord відмовив у виконанні. Перевірте права бота та ієрархію ролей."
            )
        except disnake.HTTPException:
            logger.exception(
                "Discord API помилка під час %s (moderator_id=%s)",
                action_name,
                inter.author.id,
            )
            await inter.edit_original_response(
                "Не вдалося виконати дію через помилку Discord API."
            )
        else:
            logger.info(
                "Виконано модераторську дію %s (moderator_id=%s)",
                action_name,
                inter.author.id,
            )
            await inter.edit_original_response(success_message)

    @commands.slash_command(
        name="warn",
        description="Видати учаснику попередження",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(moderate_members=True),
    )
    async def warn(
        self,
        inter: disnake.ApplicationCommandInteraction,
        member: disnake.Member,
        reason: str,
    ) -> None:
        error = self._target_error(inter, member, "moderate_members")
        if error is None:
            error = self._reason_error(reason)
        if error:
            await inter.response.send_message(error, ephemeral=True)
            return

        with sqlite3.connect(DATABASE_PATH) as connection:
            cursor = connection.execute(
                """
                INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    inter.guild_id,
                    member.id,
                    inter.author.id,
                    reason.strip(),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            warning_id = cursor.lastrowid
            active_count = connection.execute(
                """
                SELECT COUNT(*) FROM warnings
                WHERE guild_id = ? AND user_id = ? AND active = 1
                """,
                (inter.guild_id, member.id),
            ).fetchone()[0]

        await inter.response.send_message(
            f"⚠️ {member.mention} отримав попередження **#{warning_id}**.\n"
            f"Причина: {reason.strip()}\n"
            f"Активних попереджень: **{active_count}**.",
            ephemeral=True,
        )
        logger.info(
            "Попередження #%s видано (guild_id=%s, user_id=%s, moderator_id=%s)",
            warning_id,
            inter.guild_id,
            member.id,
            inter.author.id,
        )

    @commands.slash_command(
        name="warnings",
        description="Переглянути попередження учасника",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(moderate_members=True),
    )
    async def warnings(
        self,
        inter: disnake.ApplicationCommandInteraction,
        member: disnake.Member,
    ) -> None:
        if not inter.author.guild_permissions.moderate_members:
            await inter.response.send_message(
                "У вас немає дозволу переглядати попередження.",
                ephemeral=True,
            )
            return

        with sqlite3.connect(DATABASE_PATH) as connection:
            connection.row_factory = sqlite3.Row
            active_count = connection.execute(
                """
                SELECT COUNT(*) FROM warnings
                WHERE guild_id = ? AND user_id = ? AND active = 1
                """,
                (inter.guild_id, member.id),
            ).fetchone()[0]
            records = connection.execute(
                """
                SELECT id, moderator_id, reason, created_at, active
                FROM warnings
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT 10
                """,
                (inter.guild_id, member.id),
            ).fetchall()

        if not records:
            await inter.response.send_message(
                f"У {member.mention} ще немає попереджень.",
                ephemeral=True,
            )
            return

        lines = [
            f"**#{record['id']}** {'активне' if record['active'] else 'скасоване'} "
            f"• <t:{int(datetime.fromisoformat(record['created_at']).timestamp())}:d>\n"
            f"Причина: {record['reason'][:180]}\n"
            f"Модератор: <@{record['moderator_id']}>"
            for record in records
        ]
        embed = disnake.Embed(
            title=f"Попередження: {member}",
            description="\n\n".join(lines)[:4000],
            colour=disnake.Colour.orange(),
        )
        embed.set_footer(text=f"Активних попереджень: {active_count} • Показано до 10")
        await inter.response.send_message(embed=embed, ephemeral=True)

    @commands.slash_command(
        name="unwarn",
        description="Скасувати попередження за його номером",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(moderate_members=True),
    )
    async def unwarn(
        self,
        inter: disnake.ApplicationCommandInteraction,
        warning_id: int,
    ) -> None:
        if not inter.author.guild_permissions.moderate_members:
            await inter.response.send_message(
                "У вас немає дозволу скасовувати попередження.",
                ephemeral=True,
            )
            return

        with sqlite3.connect(DATABASE_PATH) as connection:
            cursor = connection.execute(
                """
                UPDATE warnings
                SET active = 0, revoked_by = ?, revoked_at = ?
                WHERE id = ? AND guild_id = ? AND active = 1
                """,
                (
                    inter.author.id,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    warning_id,
                    inter.guild_id,
                ),
            )

        if cursor.rowcount == 0:
            await inter.response.send_message(
                "Активне попередження з таким номером не знайдено.",
                ephemeral=True,
            )
            return
        await inter.response.send_message(
            f"Попередження **#{warning_id}** скасовано.",
            ephemeral=True,
        )
        logger.info(
            "Попередження #%s скасовано (guild_id=%s, moderator_id=%s)",
            warning_id,
            inter.guild_id,
            inter.author.id,
        )

    @commands.slash_command(
        name="timeout",
        description="Тимчасово обмежити учаснику можливість спілкуватися",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(moderate_members=True),
    )
    async def timeout(
        self,
        inter: disnake.ApplicationCommandInteraction,
        member: disnake.Member,
        minutes: int,
        reason: str,
    ) -> None:
        error = self._target_error(inter, member, "moderate_members")
        if error is None:
            error = self._reason_error(reason)
        if error is None and not 1 <= minutes <= MAX_TIMEOUT_MINUTES:
            error = f"Тривалість має бути від 1 до {MAX_TIMEOUT_MINUTES} хвилин."
        if error:
            await inter.response.send_message(error, ephemeral=True)
            return

        await self._run_action(
            inter,
            lambda: member.timeout(
                duration=timedelta(minutes=minutes),
                reason=reason.strip(),
            ),
            f"🔇 {member.mention} отримав таймаут на **{minutes} хв**.\n"
            f"Причина: {reason.strip()}",
            "timeout",
        )

    @commands.slash_command(
        name="untimeout",
        description="Зняти таймаут з учасника",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(moderate_members=True),
    )
    async def untimeout(
        self,
        inter: disnake.ApplicationCommandInteraction,
        member: disnake.Member,
        reason: str,
    ) -> None:
        error = self._target_error(inter, member, "moderate_members")
        if error is None:
            error = self._reason_error(reason)
        if error:
            await inter.response.send_message(error, ephemeral=True)
            return

        await self._run_action(
            inter,
            lambda: member.timeout(until=None, reason=reason.strip()),
            f"🔊 Таймаут для {member.mention} знято.\nПричина: {reason.strip()}",
            "untimeout",
        )

    @commands.slash_command(
        name="kick",
        description="Вигнати учасника із сервера",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(kick_members=True),
    )
    async def kick(
        self,
        inter: disnake.ApplicationCommandInteraction,
        member: disnake.Member,
        reason: str,
    ) -> None:
        error = self._target_error(inter, member, "kick_members")
        if error is None:
            error = self._reason_error(reason)
        if error:
            await inter.response.send_message(error, ephemeral=True)
            return

        await self._run_action(
            inter,
            lambda: member.kick(reason=reason.strip()),
            f"👢 {member.mention} вигнано із сервера.\nПричина: {reason.strip()}",
            "kick",
        )

    @commands.slash_command(
        name="ban",
        description="Заблокувати учаснику доступ до сервера",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(ban_members=True),
    )
    async def ban(
        self,
        inter: disnake.ApplicationCommandInteraction,
        member: disnake.Member,
        reason: str,
    ) -> None:
        error = self._target_error(inter, member, "ban_members")
        if error is None:
            error = self._reason_error(reason)
        if error:
            await inter.response.send_message(error, ephemeral=True)
            return

        await self._run_action(
            inter,
            lambda: member.ban(
                reason=reason.strip(),
                clean_history_duration=0,
            ),
            f"🔨 {member.mention} заблоковано на сервері.\nПричина: {reason.strip()}",
            "ban",
        )

    @commands.slash_command(
        name="unban",
        description="Зняти блокування з користувача за його Discord ID",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(ban_members=True),
    )
    async def unban(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user_id: int,
        reason: str,
    ) -> None:
        if inter.guild is None:
            await inter.response.send_message(
                "Команду можна використовувати лише на сервері.",
                ephemeral=True,
            )
            return
        if not inter.author.guild_permissions.ban_members:
            await inter.response.send_message(
                "У вас немає дозволу знімати блокування.",
                ephemeral=True,
            )
            return
        if user_id <= 0:
            await inter.response.send_message(
                "Вкажіть коректний Discord ID користувача.",
                ephemeral=True,
            )
            return
        error = self._reason_error(reason)
        if error:
            await inter.response.send_message(error, ephemeral=True)
            return

        guild = inter.guild
        user = disnake.Object(id=user_id)
        await self._run_action(
            inter,
            lambda: guild.unban(user, reason=reason.strip()),
            f"Блокування з користувача з ID `{user_id}` знято.\n"
            f"Причина: {reason.strip()}",
            "unban",
        )


def setup(bot: commands.InteractionBot) -> None:
    bot.add_cog(Admin(bot))