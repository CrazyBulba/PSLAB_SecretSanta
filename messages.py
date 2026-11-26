"""
Тексты сообщений и уведомлений бота.
Меняй здесь, чтобы быстро править формулировки.
"""

PROMPTS = {
    "intro": "📝 Напишите вступительное слово.",
    "wish": "🎁 Напишите ваши пожелания к подарку.",
    "import_pairs": "🔗 Отправьте пары в формате:\n@user1:@user2 @user3:@user4",
    "amount": "💰 Укажите сумму на подарок (например: 3000 рублей или 50$)",
}


def create_success_message(code: str) -> str:
    return (
        f"✅ Игра создана!\n"
        f"GameID: {code}\n\n"
        f"Для присоединения к игре другим участникам необходимо отправить боту:\n"
        f"/join {code}"
    )


HELP_TEXT = (
    "🎅 Secret Santa Bot\n\n"
    "/create — создать игру\n"
    "/join CODE — вступить\n"
    "/mygames — мои игры\n"
    "/setwish — пожелания\n"
    "/participants — участники\n"
    "/draw — розыгрыш\n"
    "/export — экспорт пар\n"
    "/close [all] — удалить\n"
    "/import_previous — загрузить прошлые пары\n"
    "/myresult — мой результат\n"
    "/info — информация\n\n"
    "Вступительное, сумма и избегание настраиваются в меню игры (/mygames → Редактировать)."
)


def join_success(code: str, intro: str = "") -> str:
    msg = f"✅ Вы в игре {code}!"
    if intro:
        msg += f"\n\n📝 {intro}"
    return msg
