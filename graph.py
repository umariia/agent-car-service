from langgraph.prebuilt import ToolNode, InjectedState
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langchain_core.tools import Tool, BaseTool

from typing import Annotated, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

import os
import sqlite3
import shutil
from utility_func import *


# -------------------------------------------------------- DATABASE
local_file = "car_appointments.sqlite"
backup_file = "car_appointments.backup.sqlite"
db = local_file


def create_db(db_file, db_backup_file) -> None:
    db_exists = os.path.exists(db_file)
    # create db if not exists
    if not db_exists:
        with open(db_file, 'w'): pass
    conn = sqlite3.connect(db_file)
    with conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT NOT NULL PRIMARY KEY,
            "name" TEXT NOT NULL,
            surname TEXT NOT NULL,
            email VARCHAR(320) NOT NULL UNIQUE,
            phone_number VARCHAR(15) NOT NULL UNIQUE,
            status VARCHAR(7) NOT NULL,
            date_registered VARCHAR(19) NOT NULL,
            date_updated VARCHAR(19),
            date_deleted VARCHAR(19)
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cars (
            id TEXT NOT NULL PRIMARY KEY,
            license_plate VARCHAR(12) NOT NULL UNIQUE,
            manufacturer TEXT NOT NULL,
            model TEXT NOT NULL,
            "year" INTEGER NOT NULL,
            status VARCHAR(7) NOT NULL,
            user_id TEXT NOT NULL,
            user_status VARCHAR(7) NOT NULL,
            date_registered VARCHAR(19) NOT NULL,
            date_updated VARCHAR(19),
            date_deleted VARCHAR(19),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(user_status) REFERENCES users(status)
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT NOT NULL PRIMARY KEY,
            "datetime" VARCHAR(17) NOT NULL,
            problem TEXT NOT NULL,
            status VARCHAR(10) NOT NULL,
            user_id TEXT NOT NULL,
            user_status VARCHAR(7) NOT NULL,
            car_id TEXT NOT NULL,
            car_status VARCHAR(7) NOT Null,
            date_scheduled VARCHAR(19) NOT NULL,
            date_canceled VARCHAR(19),
            date_updated VARCHAR(19),
            date_deleted VARCHAR(19),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(user_status) REFERENCES users(status),
            FOREIGN KEY(car_id) REFERENCES cars(id),
            FOREIGN KEY(car_status) REFERENCES cars(status)
        )
        """)
        cursor.close()

    if not os.path.exists(db_backup_file):
        shutil.copy(db_file, db_backup_file)
    return


create_db(db_file=local_file, db_backup_file=backup_file)


# --------------------------------------------------------- TOOLS
class ScheduleAppointmentInputSchema(BaseModel):
    user_id: Annotated[str, InjectedState("user_id")]
    user_name: str = Field(description="User name")
    user_surname: str = Field(description="User surname")
    user_email: str = Field(description="User email address")
    user_phone_number: str = Field(description="User phone number (format: +#############)")
    appointment_date: str = Field(description=f"New appointment date (format: {DATE_FORMAT})")
    appointment_time: str = Field(description=f"New appointment time (format {TIME_FORMAT})")
    appointment_problem: str = Field(description="Description of user's problem")
    car_license_plate: str = Field(description="Car licence plate")
    car_manufacturer: str = Field(description="Car manufacturer")
    car_model: str = Field(description="Car model")
    car_year: str = Field(description="Car year")


class ScheduleAppointmentTool(BaseTool, BaseSettings):
    name: str = "ScheduleAppointmentTool"
    description: str = f"Schedule an appointment."
    args_schema: object = ScheduleAppointmentInputSchema

    def _run(self, user_id: Annotated[str, InjectedState("user_id")], user_name: str, user_surname: str,
             user_email: str, user_phone_number: str, appointment_date: str, appointment_time: str,
             appointment_problem: str, car_license_plate: str, car_manufacturer: str, car_model: str, car_year: str) -> str:
        """Run the tool."""
        appointment_datetime = "T".join([appointment_date, appointment_time])
        try:
            # validate data
            check_missing_data(
                user_name, user_surname, user_email, user_phone_number, appointment_datetime,
                appointment_problem, car_license_plate, car_manufacturer, car_model, car_year)
            validate_datetime(appointment_datetime)
            validate_user_email_address(user_email)
            validate_user_phone_number(user_phone_number)
        except ValidationException as e:
            return f"Error: {str(e)}"

        # create appointment and car id
        appointment_id = str(uuid.uuid4())
        car_id = str(uuid.uuid4())
        now = datetime.now().strftime(DATETIME_FORMAT)
        active_status = car_status = ActivityStatus.ACTIVE.value

        # SCHEDULE APPOINTMENT
        try:
            if user_id is None:
                raise Exception("No user_id in State.")
            # connect to database
            conn = sqlite3.connect(db)
            with conn:
                cursor = conn.cursor()
                # check if an appointment at the given date already exists
                cursor.execute(f"""SELECT DATE(datetime) FROM appointments WHERE (
                user_id = ? AND DATE(TRIM(datetime)) = ? AND {DELETED_STATUS_QUERY_APPOINTMENT_TABLE})""",
                               (user_id, appointment_date) + INVALID_APPOINTMENT_TABLE_STATUSES)
                if (_date := cursor.fetchone()) is not None:
                    return f"An appointment with the same date ({_date[0]}) already exists. You can make make only one appointment a day."

                # check if a car with the same license plate but different details (manufacturer, model...) already exists
                cursor.execute(f"""SELECT EXISTS(SELECT 1 FROM cars 
                WHERE (user_id = ? AND license_plate = ? AND (manufacturer != ? OR model != ? OR "year" != ?)
                 AND {DELETED_STATUS_QUERY_CAR_TABLE}))""",
                               (user_id, car_license_plate, car_manufacturer, car_model, car_year) + INVALID_CAR_TABLE_STATUSES)
                if cursor.fetchone()[0] != 0:
                    return "A car with the same license plate but different details (manufacturer, model...) already exists."
                # check if a car with the same license plate and the same details (manufacturer, model...) already exists
                cursor.execute(f"""SELECT id FROM cars 
                                WHERE (user_id = ? AND license_plate = ? AND manufacturer = ? AND model = ? AND "year" = ?
                                 AND {DELETED_STATUS_QUERY_CAR_TABLE})""",
                               (user_id, car_license_plate, car_manufacturer, car_model,
                                car_year) + INVALID_CAR_TABLE_STATUSES)
                if (_car_id := cursor.fetchone()) is not None:
                    # overwrite the above created car_id with the already existing car_id
                    car_id = _car_id[0]

                # insert into users
                cursor.execute("""
                INSERT OR IGNORE INTO users (id, "name", surname, email, phone_number, status, date_registered) 
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """, (user_id, user_name, user_surname, user_email, user_phone_number, ActivityStatus.ACTIVE.value, now))
                # insert into appointments
                cursor.execute("""
                INSERT INTO appointments (id, datetime, problem, status, user_id, user_status, car_id, car_status, date_scheduled)
                 VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (appointment_id, appointment_datetime, appointment_problem, ActivityStatus.SCHEDULED.value, user_id, active_status, car_id, car_status, now))
                # insert into cars
                cursor.execute("""
                INSERT OR IGNORE INTO cars (id, license_plate, manufacturer, model, "year", status, user_id, user_status, date_registered) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (car_id, car_license_plate, car_manufacturer, car_model, car_year, car_status, user_id, active_status, now))
                cursor.close()
        except Exception as e:
            print(e)
            return f"A system error occurred while scheduling appointments. If this continues, you should request human assistance."
        return "Appointment scheduled successfully."


class UpdateUserDataInputSchema(BaseModel):
    user_id: Annotated[str, InjectedState("user_id")]
    user_name: str = Field(description="New user name")
    user_surname: str = Field(description="New user surname")
    user_email: str = Field(description="New user email address")
    user_phone_number: str = Field(description="New user phone number (format: +#############)")
    appointment_date: str = Field(description=f"New appointment date (format: {DATE_FORMAT})")
    appointment_time: str = Field(description=f"New appointment time (format {TIME_FORMAT})")
    appointment_problem: str = Field(description="New appointment problem")
    car_license_plate: str = Field(description="New car licence plate")
    car_manufacturer: str = Field(description="New car manufacturer")
    car_model: str = Field(description="New car model")
    car_year: str = Field(description="New car year")
    previous_user_phone_number: str = Field(description="Previous user phone number")
    previous_appointment_date: str = Field(description="Previous appointment date")
    previous_car_license_plate: str = Field(description="Previous car licence plate")


class UpdateUserDataTool(BaseTool, BaseSettings):
    name: str = "UpdateUserDataTool"
    description: str = f"Update the user’s personal info, appointment details, and/or car info."
    args_schema: object = UpdateUserDataInputSchema

    def _run(self, user_id: Annotated[str, InjectedState("user_id")], user_name: str, user_surname: str, user_email: str, user_phone_number: str,
             appointment_date: str, appointment_time: str, appointment_problem: str, car_license_plate: str,
             car_manufacturer: str, car_model: str, car_year: str, previous_user_phone_number: str,
             previous_appointment_date: str, previous_car_license_plate: str) -> str:
        """Run the tool."""
        appointment_datetime = "T".join([appointment_date, appointment_time])
        try:
            # validate data
            check_missing_data(
                user_name, user_surname, user_email, user_phone_number, appointment_datetime,
                appointment_problem, car_license_plate, car_manufacturer, car_model, car_year)
            validate_datetime(appointment_datetime)
            validate_user_email_address(user_email)
            validate_user_phone_number(user_phone_number)
        except ValidationException as e:
            return f"Error: {str(e)}."
        try:
            if user_id is None:
                raise Exception("No user_id in State.")
            # connect to database
            conn = sqlite3.connect(db)
            with conn:
                cursor = conn.cursor()

                # GET IDs
                # get appointment_id by user_id
                cursor.execute(f"""
                SELECT id FROM appointments WHERE (user_id = ? AND DATE(datetime) = ? AND {DELETED_STATUS_QUERY_APPOINTMENT_TABLE})  
                """, (user_id, previous_appointment_date) + INVALID_APPOINTMENT_TABLE_STATUSES)
                appointment_id = cursor.fetchone()[0]

                # get car_id by user_id
                cursor.execute(f"""
                SELECT id FROM cars WHERE (user_id = ? AND license_plate = ? AND {DELETED_STATUS_QUERY_CAR_TABLE})
                """, (user_id, previous_car_license_plate) + INVALID_CAR_TABLE_STATUSES)
                car_id = cursor.fetchone()[0]

                if appointment_id is None or car_id is None:
                    return "No user found."

                # UPDATE DATA
                now = datetime.now().strftime(DATETIME_FORMAT)

                # user data
                cursor.execute(f"""
                    UPDATE users
                    SET name = ?, surname = ?, email = ?, phone_number = ?, date_updated = ?
                    WHERE (id = ? AND {DELETED_STATUS_QUERY_USER_TABLE})
                """, (user_name, user_surname, user_email, user_phone_number, now, user_id)
                               + INVALID_USER_TABLE_STATUSES)
                if cursor.rowcount == 0:
                    return "No users found."

                # appointment data
                cursor.execute(f"""
                UPDATE appointments 
                SET datetime = ?, problem = ?, date_updated = ?
                WHERE (id = ? AND {DELETED_STATUS_QUERY_APPOINTMENT_TABLE})
                """, (appointment_datetime, appointment_problem, now, appointment_id) + INVALID_APPOINTMENT_TABLE_STATUSES)
                if cursor.rowcount == 0:
                    return "No appointments found."

                # car data
                cursor.execute(f"""
                UPDATE cars 
                SET license_plate = ?, manufacturer = ?, model = ?, year = ?, date_updated = ?
                WHERE (id = ? AND {DELETED_STATUS_QUERY_CAR_TABLE})
                """, (car_license_plate, car_manufacturer, car_model, car_year, now, car_id) + INVALID_CAR_TABLE_STATUSES)
                if cursor.rowcount == 0:
                    return "No cars found."

                cursor.close()
        except Exception as e:
            print(e)
            return "A system error occurred while updating user data."
        return "User data updated successfully."


class CheckDatetimeAvailabilityInputSchema(BaseModel):
    date: str = Field(description=f"date of appointment (format: {DATE_FORMAT})")
    time: str = Field(description=f"time of appointment (format: {TIME_FORMAT})")


class CheckDatetimeAvailabilityTool(BaseTool, BaseSettings):
    name: str = "CheckDatetimeAvailabilityTool"
    description: str = f"Check if date and time are available for scheduling an appointment."
    args_schema: object = CheckDatetimeAvailabilityInputSchema

    def _run(self, date: str, time: str) -> str:
        """Run the tool."""
        date_time = "T".join([date, time])
        try:
            validate_datetime(date_time)
        except ValidationException as e:
            return f"Invalid date and time. {str(e)}. Today date: {datetime.now()}"
        return f"Valid date."


class CheckUserAppointmentDataInputSchema(BaseModel):
    user_id: Annotated[str, InjectedState("user_id")]
    phone_number: str = Field(description="User phone number")


class CheckUserAppointmentDataTool(BaseTool):
    name: str = "CheckUserAppointmentDataInputSchema"
    description: str = "Check user appointment data."
    args_schema: object = CheckUserAppointmentDataInputSchema

    def _run(self, user_id: Annotated[str, InjectedState("user_id")], phone_number: str) -> str:
        """Run the tool."""

        try:
            if user_id is None:
                raise Exception("No user_id in State.")
            # connect to the database
            conn = sqlite3.connect(db)
            with conn:
                cursor = conn.cursor()

                # CHECK DATA
                # check user data
                cursor.execute(f"""
                        SELECT name, surname, email, phone_number FROM users 
                        WHERE (id = ? AND {DELETED_STATUS_QUERY_USER_TABLE})
                        """, (user_id,) + INVALID_USER_TABLE_STATUSES)
                user_data = cursor.fetchall()

                if user_data is None or len(user_data) == 0:
                    return "User is not registered."

                user_name, user_surname, user_email, user_phone_number = user_data[0]

                final_prompt = f"Name:{user_name}, surname:{user_surname}, email:{user_email}, phone number:{user_phone_number}."

                # check appointment data
                cursor.execute(f"""
                    SELECT datetime, problem, car_id FROM appointments 
                    WHERE (user_id = ? AND {DELETED_STATUS_QUERY_APPOINTMENT_TABLE})""",
                               (user_id,) + INVALID_APPOINTMENT_TABLE_STATUSES)
                appointment_data = cursor.fetchall()

                if appointment_data is None or len(appointment_data) == 0:
                    return final_prompt + " No appointments scheduled."

                # check car data
                cursor.execute(f"""
                SELECT license_plate, manufacturer, model, "year", id FROM cars 
                WHERE (user_id = ? AND {DELETED_STATUS_QUERY_CAR_TABLE})""",
                               (user_id,) + INVALID_CAR_TABLE_STATUSES)
                car_data = cursor.fetchall()

                if car_data is None or len(car_data) == 0:
                    return final_prompt + "No cars found."

                final_prompt = ""

                # Create a dictionary to store car_id -> list of appointment numbers
                car_appointments_map = {car_id: [] for _, _, _, _, car_id in car_data}

                # User has one appointment scheduled
                if len(appointment_data) == 1:
                    appointment_datetime, appointment_problem, car_id = appointment_data[0]
                    appointment_date, appointment_time = appointment_datetime.split("T")
                    final_prompt += (
                        f" Appointment: date:{appointment_date}, time: {appointment_time}, problem:{appointment_problem}."
                    )
                    car_appointments_map[car_id].append(1)  # Associate this appointment with the car_id

                else:
                    # User has multiple appointments
                    max_appointments = 3
                    final_prompt += f"\nUser has {len(appointment_data)} appointments scheduled."
                    if len(appointment_data) > max_appointments:
                        final_prompt += f"\n(Displaying only the first {max_appointments})"

                    for i, (appointment_datetime, appointment_problem, car_id) in enumerate(
                            appointment_data[:max_appointments], start=1
                    ):
                        appointment_date, appointment_time = appointment_datetime.split("T")
                        final_prompt += (
                            f"\n{i}. date:{appointment_date}, time:{appointment_time}, problem:{appointment_problem}."
                        )
                        car_appointments_map[car_id].append(i)  # Track this appointment for the car_id

                # User has one car
                if len(car_data) == 1 and car_data[0][4] == appointment_data[0][2]:  # car_id matches appointment
                    car_license_plate, car_manufacturer, car_model, car_year, _ = car_data[0]
                    final_prompt += (
                        f" Car: licence plate:{car_license_plate}, manufacturer:{car_manufacturer}, "
                        f"model:{car_model}, year:{car_year}."
                    )

                else:
                    # User has multiple cars
                    max_cars = 3
                    final_prompt += f"\nUser has {len(car_data)} cars registered."
                    if len(car_data) > max_cars:
                        final_prompt += f"\n(Displaying only the first {max_cars})"

                    for i, (car_license_plate, car_manufacturer, car_model, car_year, car_id) in enumerate(
                            car_data[:max_cars], start=1
                    ):
                        # Get the list of appointment numbers for this car_id
                        appointment_numbers = car_appointments_map.get(car_id, [])
                        appointment_numbers_str = ", ".join(
                            str(num) for num in appointment_numbers) if appointment_numbers else "None"

                        final_prompt += (
                            f"\n{i}. licence plate:{car_license_plate}, manufacturer:{car_manufacturer}, "
                            f"model:{car_model}, year:{car_year}, scheduled for appointments: {appointment_numbers_str}."
                        )
        except Exception as e:
            print(e)
            return "A system error occurred while checking user data."
        return final_prompt


class CancelAppointmentInputSchema(BaseModel):
    user_id: Annotated[str, InjectedState("user_id")]
    appointment_date: str = Field(description="Appointment date")


class CancelAppointmentTool(BaseTool):
    name: str = "CancelAppointmentTool"
    description: str = f"Cancel an appointment."
    args_schema: object = CancelAppointmentInputSchema

    def _run(self, user_id: Annotated[str, InjectedState("user_id")], appointment_date: str) -> str:
        """Run the tool."""
        now = str(datetime.now().strftime(DATETIME_FORMAT))
        try:
            # User id
            if not user_id:
                raise Exception("User ID is missing.")

            # cancel appointment
            conn = sqlite3.connect(db)
            with conn:
                cursor = conn.cursor()

                cursor.execute(f"""
                SELECT 1 FROM appointments 
                WHERE (user_id = ? AND DATE(date_scheduled) = ? AND {DELETED_STATUS_QUERY_APPOINTMENT_TABLE})
                """, (user_id, appointment_date) + INVALID_APPOINTMENT_TABLE_STATUSES)

                cursor.execute(f"""
                    UPDATE appointments SET status = ?, date_canceled = ? 
                    WHERE (user_id = ? AND DATE(datetime) = ? AND {DELETED_STATUS_QUERY_APPOINTMENT_TABLE})
                    """, (ActivityStatus.CANCELED.value, now, user_id,
                          appointment_date) + INVALID_APPOINTMENT_TABLE_STATUSES)
                if cursor.rowcount == 0:
                    return "No appointments with such user or appointment credentials were found."
                cursor.close()
        except Exception as e:
            print(e)
            return "A system error occurred while cancelling appointment."
        return "Appointment cancelled successfully."


class DeleteUserInputSchema(BaseModel):
    user_id: Annotated[str, InjectedState("user_id")]
    phone_number: str = Field(description="User phone number")


class DeleteUserTool(BaseTool):
    name: str = "DeleteUser"
    description: str = """Delete a user. Use this to completely delete users (their cars and appointments are deleted 
    automatically). By removing a user, you erase all information associated with them from the service, including 
    their registered cars and scheduled appointments. This action cannot be undone. Note: this does not erase only
    specific information (eg. only cars), but everything: user, their car and appointment!"""
    arg_schema: object = DeleteUserInputSchema

    def _run(self, user_id: Annotated[str, InjectedState("user_id")], phone_number: str) -> str:
        """Run the tool."""
        now = str(datetime.now().strftime(DATETIME_FORMAT))
        try:
            # User id
            if not user_id:
                raise Exception("User ID is missing.")

            # delete user
            conn = sqlite3.connect(local_file)
            with conn:
                cursor = conn.cursor()
                deleted_status = ActivityStatus.DELETED.value

                cursor.execute(f"""UPDATE appointments SET status = ?, date_deleted = ? WHERE user_id = ?""",
                               (deleted_status, now, user_id))
                if cursor.rowcount == 0:
                    raise Exception("No appointments with such user_id found.")
                cursor.execute(f"""UPDATE cars SET status = ?, date_deleted = ? WHERE user_id = ?""",
                               (deleted_status, now, user_id))
                if cursor.rowcount == 0:
                    raise Exception("No cars with such user_id found.")
                cursor.execute(f"""UPDATE users SET status = ?, date_deleted = ? WHERE id = ?""",
                               (deleted_status, now, user_id))
                if cursor.rowcount == 0:
                    raise Exception("No users with such user_id found.")
                cursor.close()
        except Exception as e:
            print(e)
            return "Some error occurred while deleting user data. If this continues, you should request human assistance."
        return "User removed successfully."


def service_data():
    """Gets data about the service (working hours, location)."""
    return """
    Working hours: monday to friday 9:00-17:00; Location: US, CA, San Francisco; Coordinates: [123456789, -987654321] 
    """


schedule_appointment_tool = ScheduleAppointmentTool()
update_user_data_tool = UpdateUserDataTool()
check_datetime_availability_tool = CheckDatetimeAvailabilityTool()
cancel_appointment_tool = CancelAppointmentTool()
check_user_appointment_data_tool = CheckUserAppointmentDataTool()
remove_user_tool = DeleteUserTool()

service_data_tool = Tool(
    name="ServiceData",
    func=service_data,
    description="Get data about the service (working hours, location).",
    handle_tool_error=True
)


tools = [schedule_appointment_tool, update_user_data_tool, cancel_appointment_tool, check_user_appointment_data_tool,
         check_datetime_availability_tool, service_data_tool, remove_user_tool]
tool_node = ToolNode(tools)


# --------------------------------------------------------- GRAPH
class State(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str


graph = StateGraph(State)


# Decide whether to continue tool usage or end the process
def should_continue(state: State) -> Literal["tools", "__end__"]:
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:  # check if the last message has any tool calls
        return "tools"
    return "__end__"


# Invocation of the model
def _call_model(state: State):
    messages = state["messages"]
    llm = ChatOpenAI(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        streaming=True,
        stream_usage=True
    ).bind_tools(tools, parallel_tool_calls=False)
    response = llm.invoke(messages)
    return {"messages": [response]}


# Structure of the graph
graph.add_edge(START, "modelNode")
graph.add_node("tools", tool_node)
graph.add_node("modelNode", _call_model)

# Add conditional logic to determine the next step based on the state (to continue or to end)
graph.add_conditional_edges(
    "modelNode",
    should_continue,
)
graph.add_edge("tools", "modelNode")
# Compile the state graph into a runnable object
graph_runnable = graph.compile()
