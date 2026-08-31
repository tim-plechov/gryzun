"""
One-off bootstrap: create the first admin account so someone can log into
the web app and start provisioning everyone else through it.

    cd Gryzun
    python -m webapp.create_admin "Ada Lovelace" ada@example.com
"""

import sys

from webapp import data


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python -m webapp.create_admin <full name> <email>")
        raise SystemExit(1)
    full_name, email = sys.argv[1], sys.argv[2]
    user_id, temp_password = data.create_teacher_account(full_name, email, role="admin")
    print(f"Created admin {full_name} <{email}> (id={user_id})")
    print(f"Temporary password: {temp_password}")
    print("Log in and change it from the account menu.")


if __name__ == "__main__":
    main()
