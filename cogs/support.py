import disnake
from disnake.ext import commands


GUILD_ID = 1572541450489430036
CATEGORY_ID = 1574470842287530004
TICKET_CHANNEL_ID = 1574471878259769344
CREATE_TICKET_CUSTOM_ID = "atlasbot:create-ticket"
OPEN_TICKET_CUSTOM_ID = "atlasbot:close-ticket"


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
                and channel.topic == f"atlasbot-ticket:{inter.author.id}"
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
                topic=f"atlasbot-ticket:{inter.author.id}",
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
            title="Тікет підтримки відкрито",
            description=(
                f"{inter.author.mention}, опишіть свою проблему якомога детальніше. "
                "Адміністрація побачить цей канал і відповість вам тут."
            ),
            colour=disnake.Colour.green(),
        )
        await ticket_channel.send(
            content=f"{inter.author.mention}",
            embed=embed,
        )
        await ticket_channel.send(
            embed=greeting_embed,
            view=CloseTicketView(),
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


class Support(commands.Cog):
    def __init__(self, bot: commands.InteractionBot) -> None:
        self.bot = bot
        self._panel_checked = False

    async def cog_load(self) -> None:
        self.bot.add_view(CreateTicketView())
        self.bot.add_view(CloseTicketView())

    def ticket_panel_embed(self) -> disnake.Embed:
        embed = disnake.Embed(
            title="Вітаємо в каналі підтримки!",
            description="Потрібна допомога?",
            colour=disnake.Colour.dark_grey(),
        )
        embed.add_field(
            name="Знайшли баг?",
            value="Повідомте нам про несправність у роботі сервера.",
            inline=False,
        )
        embed.add_field(
            name="Виявили порушення правил?",
            value="Зверніть нашу увагу на порушення, щоб ми могли оперативно вжити заходів.",
            inline=False,
        )
        embed.add_field(
            name="Є ідея для покращення сервера?",
            value="Поділіться своїми думками та пропозиціями.",
            inline=False,
        )
        embed.add_field(
            name="",
            value=(
                "Щоб створити тікет, натисніть кнопку «Створити тікет». "
                "Після цього відкриється спеціальний канал, де ви можете залишити "
                "своє повідомлення — скаргу, ідею, опис бага або запитання."
            ),
            inline=False,
        )
        embed.set_footer(text="AtlasBot • Техпідтримка")
        return embed

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

        owner_id = None
        if channel.topic and channel.topic.startswith("atlasbot-ticket:"):
            try:
                owner_id = int(channel.topic.removeprefix("atlasbot-ticket:"))
            except ValueError:
                owner_id = None

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


def setup(bot: commands.InteractionBot) -> None:
    bot.add_cog(Support(bot))
