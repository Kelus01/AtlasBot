import logging

import disnake
from disnake.ext import commands

from support_ai.llm import SupportAIError, ask_support


GUILD_ID = 1572541450489430036
CATEGORY_ID = 1574470842287530004
TICKET_CHANNEL_ID = 1574471878259769344
CREATE_TICKET_CUSTOM_ID = "atlasbot:create-ticket"
OPEN_TICKET_CUSTOM_ID = "atlasbot:close-ticket"
AI_ASSISTANT_CUSTOM_ID = "atlasbot:choose-ai"
ADMIN_ASSISTANT_CUSTOM_ID = "atlasbot:choose-admin"
HUMAN_ROLE_ID = 1574481575054278717
SERVER_INFO_COMMANDS = {"!serverinfo", "!server-info"}
logger = logging.getLogger(__name__)


def ticket_topic(owner_id: int, mode: str = "choice") -> str:
    return f"atlasbot-ticket:{owner_id}:mode:{mode}"


def parse_ticket_topic(topic: str | None) -> tuple[int | None, str]:
    if not topic or not topic.startswith("atlasbot-ticket:"):
        return None, "none"
    try:
        parts = topic.split(":")
        owner_id = int(parts[1])
        mode = "choice"
        if len(parts) >= 4 and parts[2] == "mode":
            mode = parts[3]
        return owner_id, mode
    except (IndexError, ValueError):
        return None, "none"


def message_history_content(message: disnake.Message) -> str:
    parts = [message.content.strip()] if message.content.strip() else []
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title.strip())
        if embed.description:
            parts.append(embed.description.strip())
        parts.extend(
            f"{field.name}: {field.value}"
            for field in embed.fields
            if field.name.strip() or field.value.strip()
        )
    return "\n".join(part for part in parts if part)[:3000]


class TicketModal(disnake.ui.Modal):
    def __init__(self, bot: commands.InteractionBot) -> None:
        self.bot = bot
        components = [
            disnake.ui.TextInput(
                label="Тема звернення",
                placeholder="Коротко опишіть, з чим потрібна допомога",
                custom_id="ticket_subject",
                style=disnake.TextInputStyle.short,
                max_length=100,
                required=True,
            ),
            disnake.ui.TextInput(
                label="Опис проблеми",
                placeholder="Що сталося? Коли це почалося? Як відтворити проблему?",
                custom_id="ticket_description",
                style=disnake.TextInputStyle.paragraph,
                max_length=1500,
                required=True,
            ),
        ]
        super().__init__(
            title="Створення тікету підтримки",
            custom_id="atlasbot:ticket-modal",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        guild = inter.guild
        if guild is None:
            await inter.response.send_message(
                "Цю дію можна виконувати лише на сервері.",
                ephemeral=True,
            )
            return

        await inter.response.defer(ephemeral=True)

        category = guild.get_channel(CATEGORY_ID)
        if not isinstance(category, disnake.CategoryChannel):
            await inter.edit_original_response(
                "Не знайдено налаштовану категорію тікетів."
            )
            return

        existing_ticket = next(
            (
                channel
                for channel in category.text_channels
                if isinstance(channel, disnake.TextChannel)
                and parse_ticket_topic(channel.topic)[0] == inter.author.id
            ),
            None,
        )
        if existing_ticket is not None:
            await inter.edit_original_response(
                f"У вас вже є відкритий тікет: {existing_ticket.mention}"
            )
            return

        subject = inter.text_values["ticket_subject"].strip()
        description = inter.text_values["ticket_description"].strip()

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            guild.me: disnake.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

        try:
            ticket_channel = await guild.create_text_channel(
                name=f"ticket-{inter.author.id}",
                category=category,
                    topic=ticket_topic(inter.author.id, "choice"),
                overwrites=overwrites,
                reason=f"Тікет підтримки для {inter.author}",
            )
        except disnake.HTTPException as error:
            await inter.edit_original_response(
                f"Не вдалося створити канал тікету: {error}"
            )
            return

        embed = disnake.Embed(
            title=f"Тікет: {subject}",
            description=description,
            colour=disnake.Colour.blue(),
        )
        embed.add_field(
            name="Користувач",
            value=inter.author.mention,
            inline=True,
        )
        embed.add_field(
            name="Статус",
            value="Очікує відповіді",
            inline=True,
        )
        greeting_embed = disnake.Embed(
            title="Тікет техпідтримки відкрито",
            description=(
                f"{inter.author.mention}, як вам краще продовжити звернення?"
            ),
            colour=disnake.Colour.green(),
        )
        greeting_embed.set_footer(text="AtlasBot • Оберіть спосіб підтримки")
        await ticket_channel.send(
            content=f"{inter.author.mention}",
            embed=embed,
        )
        await ticket_channel.send(
            embed=greeting_embed,
            view=SupportChoiceView(),
        )
        await inter.edit_original_response(
            content=f"Тікет створено: {ticket_channel.mention}"
        )


class CreateTicketView(disnake.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            disnake.ui.Button(
                label="Створити тікет",
                style=disnake.ButtonStyle.primary,
                emoji="🎫",
                custom_id=CREATE_TICKET_CUSTOM_ID,
            )
        )

    async def on_error(
        self,
        error: Exception,
        item: disnake.ui.Item,
        inter: disnake.MessageInteraction,
    ) -> None:
        await inter.followup.send(
            "Сталася помилка при обробці кнопки.",
            ephemeral=True,
        )


class CloseTicketView(disnake.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            disnake.ui.Button(
                label="Закрити тікет",
                style=disnake.ButtonStyle.danger,
                emoji="🔒",
                custom_id=OPEN_TICKET_CUSTOM_ID,
            )
        )


class SupportChoiceView(disnake.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            disnake.ui.Button(
                label="Спілкуватись з ШІ-асистентом",
                style=disnake.ButtonStyle.primary,
                emoji="🤖",
                custom_id=AI_ASSISTANT_CUSTOM_ID,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Почекати адміністратора",
                style=disnake.ButtonStyle.secondary,
                emoji="👤",
                custom_id=ADMIN_ASSISTANT_CUSTOM_ID,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Закрити тікет",
                style=disnake.ButtonStyle.danger,
                emoji="🔒",
                custom_id=OPEN_TICKET_CUSTOM_ID,
            )
        )


class AIResponseView(disnake.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            disnake.ui.Button(
                label="Почекати адміністратора",
                style=disnake.ButtonStyle.secondary,
                emoji="👤",
                custom_id=ADMIN_ASSISTANT_CUSTOM_ID,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Закрити тікет",
                style=disnake.ButtonStyle.danger,
                emoji="🔒",
                custom_id=OPEN_TICKET_CUSTOM_ID,
            )
        )


class Support(commands.Cog):
    def __init__(self, bot: commands.InteractionBot) -> None:
        self.bot = bot
        self._panel_checked = False

    async def cog_load(self) -> None:
        self.bot.add_view(CreateTicketView())
        self.bot.add_view(CloseTicketView())
        self.bot.add_view(SupportChoiceView())
        self.bot.add_view(AIResponseView())

    def ticket_panel_embed(self) -> disnake.Embed:
        embed = disnake.Embed(
            title="Техпідтримка Minecraft-сервера Atlas",
            description="Зустріли проблему на сервері або у грі?",
            colour=disnake.Colour.dark_green(),
        )
        embed.add_field(
            name="Проблема з сервером",
            value="Розкажіть про помилку при вході, лаги або відключення.",
            inline=False,
        )
        embed.add_field(
            name="Скарга або порушення",
            value="Опишіть обставини та прикріпіть відео, скриншоти або інші докази.",
            inline=False,
        )
        embed.add_field(
            name="Пропозиція для проекту",
            value="Поділіться ідеєю покращення серверів або ігрового процесу.",
            inline=False,
        )
        embed.add_field(
            name="Як створити тікет",
            value=(
                "Щоб створити тікет, натисніть кнопку «Створити тікет». "
                "Потім оберіть ШІ-асистента або очікування адміністратора."
            ),
            inline=False,
        )
        embed.set_footer(text="Atlas • Техпідтримка Minecraft-сервера")
        return embed

    def server_info_embed(self) -> disnake.Embed:
        embed = disnake.Embed(
            title="Інформація про сервер Testia",
            colour=disnake.Colour.dark_green(),
            description="Приєднуйся до гри та пригод на Testia!",
        )
        embed.add_field(name="Назва", value="Testia", inline=True)
        embed.add_field(name="IP-адреса", value="`mc.testia.net`", inline=True)
        embed.add_field(name="Версія Minecraft", value="`1.21.6`", inline=True)
        embed.add_field(
            name="Моди",
            value=(
                "Обов'язкових модів немає — можна грати без них. "
                "За бажанням дозволені моди-помічники, наприклад Litematica. "
                "Для інших модів дотримуйся правил сервера."
            ),
            inline=False,
        )
        return embed

    async def send_server_info(self, message: disnake.Message) -> None:
        if message.guild is None or not message.author.guild_permissions.manage_guild:
            return
        if not isinstance(message.channel, disnake.TextChannel):
            return

        await message.channel.send(embed=self.server_info_embed())
        try:
            await message.delete()
        except disnake.Forbidden:
            logger.exception(
                "Не вдалося видалити виклик !serverinfo; "
                "боту потрібен дозвіл Manage Messages у каналі %s",
                message.channel.id,
            )
        except disnake.HTTPException:
            logger.exception(
                "Помилка Discord API під час видалення виклику !serverinfo"
            )

    async def ensure_ticket_panel(self) -> None:
        if self._panel_checked:
            return
        self._panel_checked = True

        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return

        channel = guild.get_channel(TICKET_CHANNEL_ID)
        if not isinstance(channel, disnake.TextChannel):
            return

        async for message in channel.history(limit=50):
            if message.author.id == self.bot.user.id and any(
                component.custom_id == CREATE_TICKET_CUSTOM_ID
                for row in message.components
                for component in row.children
            ):
                return

        await channel.send(
            embed=self.ticket_panel_embed(),
            view=CreateTicketView(),
        )

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message) -> None:
        if message.author.bot:
            return
        if not isinstance(message.channel, disnake.TextChannel):
            return
        if message.content.strip().lower() in SERVER_INFO_COMMANDS:
            await self.send_server_info(message)
            return

        owner_id, mode = parse_ticket_topic(message.channel.topic)
        if owner_id is None:
            return
        if mode != "ai":
            return
        if not message.content.strip():
            return

        history: list[dict[str, str]] = []
        async for previous in message.channel.history(limit=20, before=message):
            content = message_history_content(previous)
            if not content:
                continue
            role = "assistant" if previous.author.bot else "user"
            history.append({"role": role, "content": content})
        history.reverse()

        async with message.channel.typing():
            try:
                answer, model, elapsed = await ask_support(
                    message.content,
                    history,
                )
            except SupportAIError as error:
                await message.reply(error.message, mention_author=False)
                return
            except Exception:
                await message.reply(
                    "Сталася неочікувана помилка при зверненні до помічника.",
                    mention_author=False,
                )
                return

        embed = disnake.Embed(
            description=answer,
            colour=disnake.Colour.blurple(),
        )
        embed.set_footer(text=f"ШІ-асистент • {model} • {elapsed:.3f} c")
        await message.reply(embed=embed, mention_author=True, view=AIResponseView())

    async def start_ai_support(
        self,
        inter: disnake.MessageInteraction,
    ) -> None:
        channel = inter.channel
        if not isinstance(channel, disnake.TextChannel):
            await inter.response.send_message(
                "Цю дію можна виконувати лише всередині тікету.",
                ephemeral=True,
            )
            return

        owner_id, _ = parse_ticket_topic(channel.topic)
        if owner_id is None:
            await inter.response.send_message(
                "Не вдалося визначити тікет.",
                ephemeral=True,
            )
            return
        if inter.author.id != owner_id:
            await inter.response.send_message(
                "Спосіб підтримки може обрати лише автор тікету.",
                ephemeral=True,
            )
            return

        await channel.edit(topic=ticket_topic(owner_id, "ai"))

        initial_request = ""
        async for message in channel.history(limit=20):
            if message.author.bot and message.embeds:
                embed = message.embeds[0]
                if embed.title and embed.title.startswith("Тікет:"):
                    initial_request = (
                        f"{embed.title}\n{embed.description or ''}"
                    )
                    break

        await inter.response.defer(ephemeral=True)
        async with channel.typing():
            try:
                answer, model, elapsed = await ask_support(
                    (
                        "Користувач створив тікет і обрав ШІ-асистента. "
                        "Проаналізуй опис тікету та почни діалог:\n"
                        f"{initial_request}"
                    )
                )
            except SupportAIError as error:
                await channel.send(
                    embed=disnake.Embed(
                        title="ШІ-асистент тимчасово недоступний",
                        description=error.message,
                        colour=disnake.Colour.red(),
                    ),
                    view=AIResponseView(),
                )
                await inter.edit_original_response(
                    content="Спроба звернення до ШІ-асистента виконана."
                )
                return

        embed = disnake.Embed(
            title="ШІ-асистент",
            description=answer,
            colour=disnake.Colour.blurple(),
        )
        embed.set_footer(text=f"{model} • {elapsed:.3f} c")
        await channel.send(
            embed=embed,
            view=AIResponseView(),
        )
        await inter.edit_original_response(
            content="ШІ-асистент почав діалог."
        )

    async def wait_for_admin(
        self,
        inter: disnake.MessageInteraction,
    ) -> None:
        channel = inter.channel
        if not isinstance(channel, disnake.TextChannel):
            await inter.response.send_message(
                "Цю дію можна виконувати лише всередині тікету.",
                ephemeral=True,
            )
            return

        owner_id, _ = parse_ticket_topic(channel.topic)
        if owner_id is None:
            await inter.response.send_message(
                "Не вдалося визначити тікет.",
                ephemeral=True,
            )
            return
        if inter.author.id != owner_id:
            await inter.response.send_message(
                "Цей вибір може зробити лише автор тікету.",
                ephemeral=True,
            )
            return

        await channel.edit(topic=ticket_topic(owner_id, "human"))

        role = inter.guild.get_role(HUMAN_ROLE_ID)
        role_mention = role.mention if role else f"<@&{HUMAN_ROLE_ID}>"
        embed = disnake.Embed(
            title="Очікування адміністратора",
            description=(
                f"{role_mention}, у тікеті потрібна допомога людини. "
                "ШІ-асистент більше не буде відповідати на повідомлення цього каналу."
            ),
            colour=disnake.Colour.orange(),
        )
        embed.set_footer(text="AtlasBot • Режим очікування")
        await inter.response.send_message(
            embed=embed,
            view=CloseTicketView(),
        )

    async def close_ticket(
        self,
        inter: disnake.MessageInteraction,
    ) -> None:
        channel = inter.channel
        if not isinstance(channel, disnake.TextChannel):
            await inter.response.send_message(
                "Цю команду можна використовувати лише всередині тікету.",
                ephemeral=True,
            )
            return

        owner_id, _ = parse_ticket_topic(channel.topic)

        can_close = (
            inter.author.id == owner_id
            or inter.author.guild_permissions.manage_channels
        )
        if not can_close:
            await inter.response.send_message(
                "Закрити тікет можуть лише його автор або модератор.",
                ephemeral=True,
            )
            return

        await inter.response.send_message(
            "Тікет закривається..."
        )
        await channel.delete(reason=f"Тікет закрито користувачем {inter.author}")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.ensure_ticket_panel()

    @commands.slash_command(
        name="ticket-panel",
        description="Відправити повідомлення для створення тікетів",
        guild_ids=[GUILD_ID],
        default_member_permissions=disnake.Permissions(manage_guild=True),
    )
    async def ticket_panel(
        self,
        inter: disnake.ApplicationCommandInteraction,
    ) -> None:
        channel = inter.guild.get_channel(TICKET_CHANNEL_ID)
        if not isinstance(channel, disnake.TextChannel):
            await inter.response.send_message(
                "Не знайдено канал для створення тікетів.",
                ephemeral=True,
            )
            return

        await channel.send(
            embed=self.ticket_panel_embed(),
            view=CreateTicketView(),
        )
        await inter.response.send_message(
            f"Панель тікетів відправлено в {channel.mention}.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_button_click(
        self,
        inter: disnake.MessageInteraction,
    ) -> None:
        if inter.component.custom_id == CREATE_TICKET_CUSTOM_ID:
            await inter.response.send_modal(modal=TicketModal(self.bot))
        elif inter.component.custom_id == OPEN_TICKET_CUSTOM_ID:
            await self.close_ticket(inter)
        elif inter.component.custom_id == AI_ASSISTANT_CUSTOM_ID:
            await self.start_ai_support(inter)
        elif inter.component.custom_id == ADMIN_ASSISTANT_CUSTOM_ID:
            await self.wait_for_admin(inter)


def setup(bot: commands.InteractionBot) -> None:
    bot.add_cog(Support(bot))
