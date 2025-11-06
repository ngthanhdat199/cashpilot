import src.track_py.const as const
from src.track_py.utils.category import category_display


def get_keywords_response() -> str:
    keywords = const.LIST_KEYWORDS
    message_lines = [f"{category_display['keywords']}\n"]

    for category, words in keywords.items():
        icon = const.CATEGORY_ICONS.get(category, "🏷️")
        category_name = const.CATEGORY_NAMES.get(category, category)

        # Category header
        message_lines.append(f"{icon} {category_name}")
        message_lines.append("-" * 35)

        # Format keywords in 2–3 columns
        per_line = 3
        for i in range(0, len(words), per_line):
            chunk = " • ".join(words[i : i + per_line])
            message_lines.append(f"   {chunk}")

        message_lines.append("")  # Add spacing between categories

    # Wrap entire message in a Telegram code block
    response = "```\n" + "\n".join(message_lines) + "\n```"

    return response
