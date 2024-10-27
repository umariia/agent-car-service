import re
from datetime import datetime

tutorial_questions = [
    "Hi there, what time is my appointment?",
    "Am i allowed to update my appointment to something sooner? I want to update it to later today.",
    "Update my appointment to sometime next week then",
    "The next available option is great",
    "what about the location?",
    "",
    "OK could you place a reservation for your recommended hotel? It sounds nice.",
    "yes go ahead and book anything that's moderate expense and has availability.",
    "Now for a car, what are my options?",
    "Awesome let's just get the cheapest option. Go ahead and book for 7 days",
    "Cool so now what recommendations do you have on excursions?",
    "Are they available while I'm there?",
    "interesting - i like the museums, what options are there? ",
    "OK great pick one and book it for my second day there.",
]


def user_prompt_validation(user_prompt: str, max_tokens: int) -> str:
    if len(user_prompt) > max_tokens:
        return "User prompt too long."


def check_missing_user_data(user_data: dict) -> str:
    for value in user_data.keys():
        if value:
            return f"User's data is missing {value}."
    return "User's data is not missing."


def validate_user_gmail_address(user_gmail: str) -> str:
    match = re.match('^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$', user_gmail)
    if match is None:
        return "Invalid gmail address."
    return "Valid gmail address."


def validate_user_phone_number(user_phone_number: str) -> str:
    match = re.match('^(\+\d{1,3}\s)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}$', user_phone_number)
    if user_phone_number[2] == user_phone_number[3] == 0:
        return "Invalid phone number."
    if match is None:
        return "Invalid phone number."

    # refactor user phone number to match +### ###-###-#### pattern
    if re.match('^(\+\d{1,3}\s)?\(?\d{3}\)?[-]\d{3}[-]\d{4}$', user_phone_number) is None:      ############# is not None ???
        refactored_user_phone_number = re.sub("(?:\+1[\- /]?)?([2-9]\d{2})[\- /]?([2-9]\d{2})[\- /]?(\d{4})", user_phone_number)

        return "Valid phone number. Refactored phone number: " + refactored_user_phone_number
    return "Valid phone number"


# def validate_time_format(time_str, time_format: str = "%H:%M", time_format_user: str = "HH:MM") -> str | None:
#     try:
#         datetime.strptime(time_str, time_format)
#     except ValueError as e:
#         print(f"Error parsing time format: {e}")
#         return f"Invalid time format. Must be {time_format_user}."


# def validate_date_format(date_str, date_format: str = "%Y-%m-%d", date_format_user: str = "YYYY-MM-DD") -> str | None:
#     try:
#         datetime.strptime(date_str, date_format)
#     except ValueError as e:
#         print(f"Error parsing date format: {e}")
#         return f"Invalid date format. Must be {date_format_user}."
