import os
import subprocess
import sys
import time

# 需要修改为你电脑里实际的宽带/拨号连接名。
# 例如："宽带连接"、"PPPoE"、"ChinaNet" 等。
DEFAULT_CONNECTION = "宽带连接"
STARTUP_SHORTCUT_NAME = "open_Internet.lnk"
DEFAULT_DELAY_SECONDS = 10
CREDENTIAL_PREFIX = "ASCIIHEX:"
CREDENTIAL_KEYS = {"账号", "密码"}


def get_startup_dir() -> str:
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def get_startup_shortcut_path() -> str:
    return os.path.join(get_startup_dir(), STARTUP_SHORTCUT_NAME)


def get_credentials_path() -> str:
    user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    return os.path.join(user_profile, "Documents", "宽带账号.txt")


def read_account_data(path: str) -> dict:
    fields = {}
    needs_credential_migration = False
    try:
        with open(path, "r", encoding="utf-8") as account_file:
            for line in account_file:
                key, separator, value = line.rstrip("\r\n").partition("=")
                if separator:
                    if key in CREDENTIAL_KEYS:
                        if value.startswith(CREDENTIAL_PREFIX):
                            try:
                                value = bytes.fromhex(value[len(CREDENTIAL_PREFIX):]).decode("utf-8")
                            except (ValueError, UnicodeDecodeError):
                                value = ""
                        elif value:
                            needs_credential_migration = True
                    fields[key] = value
    except (OSError, UnicodeError):
        pass
    if needs_credential_migration:
        fields["_credentials_need_encoding"] = "是"
    return fields


def save_account_data(path: str, fields: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    field_order = ("账号", "密码", "等待秒数", "是否修改启动时间", "是否修改名称", "宽带名称")
    ordered_keys = [key for key in field_order if key in fields]
    ordered_keys.extend(key for key in fields if key not in field_order)
    with open(path, "w", encoding="utf-8") as account_file:
        for key in ordered_keys:
            if key == "_credentials_need_encoding":
                continue
            value = str(fields[key])
            if key in CREDENTIAL_KEYS and not value.startswith(CREDENTIAL_PREFIX):
                value = CREDENTIAL_PREFIX + value.encode("utf-8").hex()
            account_file.write(f"{key}={value}\n")


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes", "n", "no"):
            return answer in ("y", "yes")
        print("请输入 Y 或 N。")


def read_credentials(path: str) -> dict | None:
    fields = read_account_data(path)
    username = fields.get("账号", "").strip()
    password = fields.get("密码", "")
    if username and password:
        return {"username": username, "password": password}
    return None


def load_credentials() -> dict:
    credentials_path = get_credentials_path()
    fields = read_account_data(credentials_path)
    credentials = read_credentials(credentials_path)
    if credentials:
        if fields.pop("_credentials_need_encoding", None):
            save_account_data(credentials_path, fields)
        return credentials

    print(f"账号文件不存在账号信息或内容不完整，请输入后保存：{credentials_path}")
    username = fields.get("账号", "").strip()
    while not username:
        username = input("请输入宽带账号: ").strip()
        if not username:
            print("宽带账号不能为空。")

    password = fields.get("密码", "")
    while not password:
        password = input("请输入宽带密码（输入内容会显示）: ").strip()
        if not password:
            print("宽带密码不能为空。")

    fields["账号"] = username
    fields["密码"] = password
    save_account_data(credentials_path, fields)
    print(f"宽带账号信息已保存：{credentials_path}")
    return {"username": username, "password": password}


def load_settings(prompt: bool) -> dict:
    settings_path = get_credentials_path()
    fields = read_account_data(settings_path)
    changed = False

    try:
        delay_seconds = int(fields["等待秒数"])
        if delay_seconds < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        if not prompt:
            delay_seconds = DEFAULT_DELAY_SECONDS
        else:
            modify_delay = ask_yes_no(f"是否修改启动等待时间？默认 {DEFAULT_DELAY_SECONDS} 秒 (Y/N): ")
            delay_seconds = DEFAULT_DELAY_SECONDS
            if modify_delay:
                while True:
                    try:
                        delay_seconds = int(input("请输入启动前等待秒数: ").strip())
                        if delay_seconds < 0:
                            raise ValueError
                        break
                    except ValueError:
                        print("请输入大于或等于 0 的整数。")
            fields["是否修改启动时间"] = "是" if modify_delay else "否"
            fields["等待秒数"] = str(delay_seconds)
            changed = True

    connection_name = fields.get("宽带名称", "").strip()
    if fields.get("是否修改名称") not in ("是", "否") or not connection_name:
        if not prompt:
            connection_name = DEFAULT_CONNECTION
            fields["是否修改名称"] = "否"
        else:
            modify_name = ask_yes_no(
                f"是否修改本机宽带名称？默认名称为“{DEFAULT_CONNECTION}”(Y/N): "
            )
            connection_name = DEFAULT_CONNECTION
            if modify_name:
                entered_name = input("请输入本机宽带名称: ").strip()
                if entered_name:
                    connection_name = entered_name
            fields["是否修改名称"] = "是" if modify_name else "否"
        fields["宽带名称"] = connection_name
        changed = True

    if changed:
        save_account_data(settings_path, fields)
        print(f"设置已保存：{settings_path}")

    return {"delay_seconds": delay_seconds, "connection_name": connection_name}


def add_startup_shortcut(exe_path: str) -> bool:
    """将程序加入 Windows 开机自启动，并命名为 open_Internet。"""
    if os.name != "nt":
        return False

    startup_dir = get_startup_dir()
    os.makedirs(startup_dir, exist_ok=True)
    shortcut_path = get_startup_shortcut_path()
    workdir = os.path.dirname(exe_path)

    ps_command = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
        f"$s.TargetPath = '{exe_path}'; "
        f"$s.Arguments = '--startup'; "
        f"$s.WorkingDirectory = '{workdir}'; "
        f"$s.IconLocation = '{exe_path},0'; "
        "$s.Save()"
    )

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0 and os.path.exists(shortcut_path):
        print(f"已加入开机自启动：{shortcut_path}")
        return True

    print(f"加入开机自启动失败。请检查目录：{startup_dir}")
    if result.stderr:
        print(result.stderr.strip())
    elif result.stdout:
        print(result.stdout.strip())
    return False


def prompt_for_startup(exe_path: str):
    """检测是否已有启动项；若无，则询问是否加入自启动。"""
    shortcut_path = get_startup_shortcut_path()
    if os.path.exists(shortcut_path):
        print(f"已检测到开机自启动文件：{shortcut_path}，将跳过询问。")
        return True

    while True:
        answer = input("是否将此程序加入 Windows 开机自启动？(Y/N): ").strip().lower()
        if answer in ("y", "yes"):
            if add_startup_shortcut(exe_path):
                return True
            return False
        if answer in ("n", "no"):
            print("已选择不加入开机自启动。")
            return True
        print("请输入 Y 或 N。")


def open_dial_up_settings():
    """打开 Windows 设置 -> 网络和 Internet -> 拨号。"""
    if os.name != "nt":
        return

    subprocess.Popen(["explorer.exe", "ms-settings:network-dialup"], shell=True)


def connect_to_broadband(connection_name: str, credentials: dict):
    """尝试连接目标宽带。"""
    if os.name != "nt":
        return

    try:
        subprocess.run(
            ["rasdial", connection_name, credentials["username"], credentials["password"]],
            check=False,
        )
    except Exception:
        pass


def run_network_operation(settings: dict, credentials: dict):
    time.sleep(settings["delay_seconds"])
    open_dial_up_settings()
    time.sleep(3)
    connect_to_broadband(settings["connection_name"], credentials)


def main():
    exe_path = os.path.abspath(sys.argv[0])

    if "--startup" in sys.argv[1:]:
        settings = load_settings(prompt=False)
        credentials = load_credentials()
        run_network_operation(settings, credentials)
        return

    print("正在启动网络拨号辅助程序...\n")
    settings = load_settings(prompt=True)
    credentials = load_credentials()
    if not prompt_for_startup(exe_path):
        print("未成功加入开机自启动，已停止后续操作。")
        input("按 Enter 键退出...")
        return

    run_network_operation(settings, credentials)
    input("按 Enter 键退出...")


if __name__ == "__main__":
    main()
