import snowflake.snowpark as snowpark


def main(session: snowpark.Session, args: dict = {}) -> dict:
    return {"hello": "from pinky-provider", "account": session.get_current_account()}
