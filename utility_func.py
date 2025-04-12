import re
import uuid
from datetime import datetime, timedelta
from enum import Enum

# Model
MODEL_NAME = "gpt-4o-mini"  # INPUT TOKEN LIMIT: 124k, OUTPUT TOKEN LIMIT: 4096 (or 16,384)
TEMPERATURE = 0.0
MAX_TOKENS = 4000
MAX_TOKENS_USER_PROMPT = 100
MAX_LENGTH_USER_PROMPT = 200


# Database statuses
class ActivityStatus(Enum):
    ACTIVE = "active"
    DELETED = "deleted"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELED = "canceled"


# invalid statuses
_INVALID_USER_STATUSES = (ActivityStatus.DELETED.value,)
_INVALID_CAR_STATUSES = (ActivityStatus.DELETED.value,)
_INVALID_APPOINTMENT_STATUSES = (ActivityStatus.COMPLETED.value, ActivityStatus.CANCELED.value,
                                 ActivityStatus.DELETED.value)

# check for deleted statuses queries
_DELETED_STATUS_QUERY_USER = f"status NOT IN ({', '.join('?' for _ in _INVALID_USER_STATUSES)})"
_DELETED_STATUS_QUERY_CAR = f"status NOT IN ({', '.join('?' for _ in _INVALID_CAR_STATUSES)})"
_DELETED_STATUS_QUERY_APPOINTMENT = f"status NOT IN ({', '.join('?' for _ in _INVALID_APPOINTMENT_STATUSES)})"

# queries based on the structure of database tables for easier use
DELETED_STATUS_QUERY_USER_TABLE = f"({_DELETED_STATUS_QUERY_USER})"
DELETED_STATUS_QUERY_CAR_TABLE = f"({_DELETED_STATUS_QUERY_CAR} AND user_{_DELETED_STATUS_QUERY_USER})"
DELETED_STATUS_QUERY_APPOINTMENT_TABLE = \
    f"({_DELETED_STATUS_QUERY_APPOINTMENT} AND car_{_DELETED_STATUS_QUERY_CAR} AND user_{_DELETED_STATUS_QUERY_USER})"


# parameters to pass to queries above
INVALID_USER_TABLE_STATUSES = _INVALID_USER_STATUSES
INVALID_CAR_TABLE_STATUSES = _INVALID_CAR_STATUSES + _INVALID_USER_STATUSES
INVALID_APPOINTMENT_TABLE_STATUSES = _INVALID_APPOINTMENT_STATUSES + _INVALID_CAR_STATUSES + _INVALID_USER_STATUSES

# possible values the agent might put in as missing data
POSSIBLE_MISSING_DATA_VALUES = ("", "...", "N/A")


# Custom exceptions
class TokenExceededException(Exception):
    pass


class ValidationException(Exception):
    pass


# Validation
def user_prompt_validation(user_prompt: str) -> None:
    """Validate user input to the model."""
    if len(user_prompt) > 200:
        raise ValidationException("Your prompt too long!")


def validate_user_email_address(user_email: str) -> None:
    """Check if the provided email address is valid."""
    match = re.match('^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$', user_email)
    if match is None:
        raise ValidationException("Invalid email address.")


def validate_user_phone_number(user_phone_number: str) -> str:
    """Check if the provided phone number is valid."""
    user_phone_number = user_phone_number.strip()
    if len(user_phone_number) > 31 or (sum(c.isdigit() for c in user_phone_number) > 15):
        raise ValidationException("Phone number is too long.")
    if "+" not in user_phone_number:
        raise ValidationException("Phone number does not have country code.")
    if sum(c.isdigit() for c in user_phone_number) < 11:
        raise ValidationException("Phon number is too short.")

    # if user_phone_number[2] == user_phone_number[3] == 0:                     ????
    #     raise ValidationException("Invalid phone number.")
    match = re.match(r'^(\+\d{1,3}[\s.-]?)(\d{3}[\s.-]?\d{3}[\s.-]?\d{4})$', user_phone_number)
    if match is None:
        raise ValidationException("Invalid phone number. Check if the carrier is present and the phone"
                                  "number is separated by space or '.' and '-' characters.")
    for char in ["-", " ", "."]:
        if char in user_phone_number:
            user_phone_number = user_phone_number.replace(char, "")
    return user_phone_number


def validate_datetime(date_time: str, datetime_format="%Y-%m-%dT%H:%M") -> None:
    """Validate date and time formats."""
    readable_datetime_format = make_datetime_format_readable(datetime_format)
    try:
        datetime.strptime(date_time, datetime_format)
    except ValueError:
        raise ValidationException(f"Invalid datetime format. Must be {readable_datetime_format}.")

    # date_time = f"{date} {time}"
    # date_time_format = f"{date_format} {time_format}"
    # if datetime.strptime(date_time, date_time_format) < datetime.now():
    #     raise ValidationException(f"Date is in the past. Date must be more than {str(datetime.now())}")

    date, time = date_time.split("T")

    date_datetime = datetime.strptime(date, "%Y-%m-%d").date()
    time_datetime = datetime.strptime(time, "%H:%M").time()

    datetime_datetime = datetime.combine(date_datetime, time_datetime)
    now = datetime.now()
    minimum_lead_time = timedelta(hours=2)
    maximum_advance_time = timedelta(days=60)

    if datetime_datetime - now > maximum_advance_time:
        raise ValidationException("Appointments cannot be scheduled more than 60 days in advance")
    if date_datetime < now.date() or (date_datetime == now.date() and time_datetime < now.time()):
        raise ValidationException("Provided date and time are in the past")
    if datetime_datetime - now < minimum_lead_time:
        raise ValidationException("Appointments must be scheduled at least 2 hour in advance")
    if not (9 <= time_datetime.hour < 18):
        raise ValidationException(f"Time is outside of working hours")
    if (17 < time_datetime.hour <= 18) and (30 < time_datetime.minute):
        raise ValidationException(f"Time is between 17:30 and 18 oclock. There's no time left for appointment")
    if date_datetime.weekday() in [5, 6]:
        raise ValidationException(f"Provided date is a {'Saturday' if date_datetime.weekday() == 5 else 'Sunday'}")
    if time_datetime.minute not in [0, 30]:
        raise ValidationException("Appointments can only be scheduled at 00 or 30 minutes past the hour")


def check_missing_data(*values, possible_missing_values=POSSIBLE_MISSING_DATA_VALUES) -> None:
    """
    Check if any of the provided values are in the list of possible missing data values.
    """
    if any(value in possible_missing_values for value in values):
        raise ValidationException("Some values are missing.")


def make_datetime_format_readable(datetime_format) -> str:
    """Reformat datetime format into a readable format. Examples: %Y-%m-%dT%H:%M:%S -> YYYY-MM-DDTHH:MM:SS."""
    date_format, time_format = datetime_format.split("T")
    readable_date_format = readable_time_format = ""
    # make readable date format
    for char in date_format.capitalize():
        if char in ["-", ":", " ", "/"]:
            readable_date_format += char
        if char.isalpha():
            readable_date_format += (char + char)
    # make readable time format
    for char in time_format.capitalize():
        if char in ["-", ":", " ", "/"]:
            readable_time_format += char
        if char.isalpha():
            readable_time_format += (char + char)
    readable_datetime_format = f"{readable_date_format}T{readable_time_format}"
    return readable_datetime_format


def create_or_ignore_user_id(cursor, phone_number: str) -> str:
    """Create new user id if it is not already present in the database, otherwise return the existing one."""
    # get id by phone_number from the database
    cursor.execute(f"""SELECT id FROM users WHERE phone_number = ? AND {DELETED_STATUS_QUERY_USER_TABLE}""",
                   (phone_number,) + INVALID_USER_TABLE_STATUSES)
    if (res := cursor.fetchone()) is None:
        return str(uuid.uuid4())
    return res[0]


# Datetime formats
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
TIME_FORMAT = "HH:MM"
DATE_FORMAT = "YYYY-MM-DD"
DATETIME_FORMAT_READABLE = make_datetime_format_readable(DATETIME_FORMAT)
