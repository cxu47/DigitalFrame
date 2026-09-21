"""Render the small form without a template-engine dependency."""

from html import escape
from importlib.resources import files
import re
from string import Template

from fastapi.responses import HTMLResponse
from ..cache import photo_month_label
from ..network.state import DISABLED


_TEMPLATE = Template(
    files("client.control").joinpath("templates/index.html").read_text(encoding="utf-8")
)

_EN = {
    "title": "DigitalFrame control",
    "slideshow_control": "Slideshow control",
    "duration_control": "Display duration",
    "seconds_per_photo": "Seconds per photo",
    "apply": "Apply",
    "folder_control": "Control by folder",
    "choose_folder": "Choose folder",
    "apply_folder": "Apply folder",
    "month_control": "Control by month",
    "apply_months": "Apply months",
    "software_update": "Software update",
    "check_updates": "Check for updates",
    "install_update": "Install update",
    "wifi_control": "Wi-Fi control",
    "wifi_access_point": "Wi-Fi access point",
    "wifi_password": "Wi-Fi password",
    "apply_wifi": "Apply Wi-Fi",
    "refresh_access_points": "Refresh access points",
    "logs_and_comments": "Logs and comments",
    "error_history": "Error history",
    "note_apply": "Changes apply from the next photo. The duration, folder, selected months, and active viewing mode are saved for the next start.",
    "note_modes": "Applying a folder or a group of months makes that viewing mode active. Both controls remain available.",
    "note_refresh": "Refresh this page after syncing to update folders, months, picture counts, and dates.",
    "note_counts": "Counts show cached pictures. Updated dates use the latest OSS modification date for the folder or its pictures (UTC).",
    "note_order": "Photos play newest first by their OSS modification date. Month buckets use that date in UTC.",
    "note_offline": "When offline, join the setup Wi-Fi shown on the slideshow and open its displayed address. Stay connected if your phone warns that this network has no internet.",
    "note_wifi_attempt": "Wi-Fi setup makes one connection attempt per submission. If it fails, reconnect to the same setup network. Cached playback continues. Refresh this page to see the latest status.",
}

_ZH = {
    "title": "DigitalFrame 控制面板",
    "slideshow_control": "幻灯片控制",
    "duration_control": "显示时长",
    "seconds_per_photo": "每张照片显示秒数",
    "apply": "应用",
    "folder_control": "按文件夹控制",
    "choose_folder": "选择文件夹",
    "apply_folder": "应用文件夹",
    "month_control": "按月份控制",
    "apply_months": "应用月份",
    "software_update": "软件更新",
    "check_updates": "检查更新",
    "install_update": "安装更新",
    "wifi_control": "Wi-Fi 控制",
    "wifi_access_point": "Wi-Fi 接入点",
    "wifi_password": "Wi-Fi 密码",
    "apply_wifi": "应用 Wi-Fi",
    "refresh_access_points": "刷新接入点",
    "logs_and_comments": "日志和说明",
    "error_history": "错误记录",
    "note_apply": "更改将从下一张照片开始生效。显示时长、文件夹、所选月份和当前浏览模式会保存供下次启动使用。",
    "note_modes": "应用文件夹或一组月份后，对应的浏览模式将启用。两种控制方式仍然可用。",
    "note_refresh": "同步后请刷新此页面，以更新文件夹、月份、照片数量和日期。",
    "note_counts": "数量表示已缓存的照片。更新日期采用文件夹或其中照片在阿里云 OSS 中的最新修改日期（UTC）。",
    "note_order": "照片按在阿里云 OSS 中的最后修改日期从新到旧播放。月份分组使用该日期的 UTC 时间。",
    "note_offline": "离线时，请连接幻灯片上显示的设置 Wi-Fi，并打开显示的地址。如果手机提示此网络无法连接互联网，请仍保持连接。",
    "note_wifi_attempt": "每次提交 Wi-Fi 设置只会尝试连接一次。如果失败，请重新连接到同一个设置网络。缓存的照片会继续播放。刷新此页面可查看最新状态。",
}

_ZH_MESSAGES = {
    "Updates have not been checked.": "尚未检查更新。",
    "Another update operation is already running.": "另一项更新操作正在运行。",
    "Unable to check GitHub for updates.": "无法从 GitHub 检查更新。",
    "Unable to interpret the update check.": "无法解析更新检查结果。",
    "Check for an available update before installing it.": "安装前请先检查可用更新。",
    "The update did not finish. Check the checkout before trying again.": "更新未完成。请检查代码目录后重试。",
    "Code was updated, but uv sync failed. Run deploy/apply-update.sh from a terminal.": "代码已更新，但 uv 同步失败。请在终端运行 deploy/apply-update.sh。",
    "Local changes appeared after the check; installation was stopped.": "检查后出现了本地更改，安装已停止。",
    "The update was stopped safely. Check the checkout from a terminal.": "更新已安全停止。请在终端检查代码目录。",
    "The local checkout is ahead of release/3.x; automatic update is disabled.": "本地代码领先于 release/3.x；自动更新已禁用。",
    "The local checkout has diverged from release/3.x; automatic update is disabled.": "本地代码与 release/3.x 已分叉；自动更新已禁用。",
    "Wi-Fi setup is not enabled on this device.": "此设备未启用 Wi-Fi 设置。",
    "Checking Wi-Fi...": "正在检查 Wi-Fi……",
    "Wi-Fi helper unavailable. Cached playback continues.": "Wi-Fi 辅助服务不可用。缓存的照片会继续播放。",
    "Wi-Fi unavailable — cached slideshow continues.": "Wi-Fi 不可用——缓存的幻灯片会继续播放。",
    "Starting Wi-Fi setup...": "正在启动 Wi-Fi 设置……",
    "Set up Wi-Fi.": "设置 Wi-Fi。",
    "Wi-Fi setup unavailable.": "Wi-Fi 设置不可用。",
    "Preparing your Wi-Fi connection attempt. Cached playback continues.": "正在准备连接 Wi-Fi。缓存的照片会继续播放。",
    "Preparing a fresh Wi-Fi scan. The setup hotspot will briefly disconnect.": "正在准备重新扫描 Wi-Fi。设置热点将短暂断开。",
    "Scanning for all nearby Wi-Fi access points.": "正在扫描附近的所有 Wi-Fi 接入点。",
    "Scan refreshed. Choose an access point and enter its password.": "扫描已刷新。请选择接入点并输入密码。",
    "Trying your Wi-Fi. Association and DHCP may take up to one minute.": "正在尝试连接 Wi-Fi。关联和 DHCP 最多可能需要一分钟。",
    "Connected. Rejoin your home Wi-Fi and open the URL on the slideshow.": "已连接。请重新连接家庭 Wi-Fi，并打开幻灯片上显示的网址。",
    "Connection attempt failed. Enter your Wi-Fi details to try again.": "连接失败。请输入 Wi-Fi 信息后重试。",
    "Wi-Fi connected. Setup becomes available if the link is lost.": "Wi-Fi 已连接。连接断开时会启用设置。",
    "Enter a positive whole number of seconds, such as 5.": "请输入正整数秒数，例如 5。",
    "Choose an existing folder or All.": "请选择现有文件夹或“全部”。",
    "Choose one or more available months.": "请选择一个或多个可用月份。",
    "Unable to save slideshow settings. Check that the board's .env is writable.": "无法保存幻灯片设置。请检查设备的 .env 文件是否可写。",
    "Refresh this page before checking for updates.": "检查更新前请刷新此页面。",
    "Refresh this page before installing an update.": "安装更新前请刷新此页面。",
    "Refresh this page before submitting Wi-Fi details.": "提交 Wi-Fi 信息前请刷新此页面。",
    "Wi-Fi setup is not available now. Refresh for current status.": "Wi-Fi 设置目前不可用。请刷新以查看当前状态。",
    "Unable to reach the Wi-Fi helper. Please try again.": "无法连接 Wi-Fi 辅助服务。请重试。",
    "Trying your Wi-Fi. Your phone will disconnect from the frame. If connection fails, reconnect to the same DigitalFrame network.": "正在尝试连接 Wi-Fi。您的手机将与相框断开。如果连接失败，请重新连接到同一个 DigitalFrame 网络。",
    "Refresh this page before requesting a Wi-Fi scan.": "请求 Wi-Fi 扫描前请刷新此页面。",
    "Wi-Fi scanning is not available now. Reconnect and refresh the page.": "Wi-Fi 扫描目前不可用。请重新连接并刷新页面。",
    "Refreshing access points. Your phone will disconnect; reconnect to the same DigitalFrame network in about 20–30 seconds.": "正在刷新接入点。您的手机将断开连接；请在约 20–30 秒后重新连接到同一个 DigitalFrame 网络。",
    "Submit the HTML form to change the folder.": "请提交 HTML 表单以更改文件夹。",
    "Submit the HTML form to change the photo months.": "请提交 HTML 表单以更改照片月份。",
    "Submit the HTML form to change the duration.": "请提交 HTML 表单以更改显示时长。",
    "Enter the SSID and password using the Wi-Fi form.": "请使用 Wi-Fi 表单输入 SSID 和密码。",
    "Refresh this page before requesting an update.": "请求更新前请刷新此页面。",
    "Unable to read that form. Please check your selection or duration and try again.": "无法读取该表单。请检查选择或显示时长后重试。",
    "Page not found. Use the forms below to control the slideshow.": "找不到页面。请使用下方表单控制幻灯片。",
    "Wi-Fi setup encountered an error. Refresh and try again.": "Wi-Fi 设置遇到错误。请刷新后重试。",
    "The control page encountered an error. Cached playback continues; try refreshing.": "控制页面遇到错误。缓存的照片会继续播放；请尝试刷新。",
    "Choose one of the listed Wi-Fi access points.": "请选择列表中的一个 Wi-Fi 接入点。",
    "Enter a Wi-Fi SSID of 1–32 bytes without control characters.": "请输入 1–32 字节且不含控制字符的 Wi-Fi SSID。",
    "Enter a WPA2 password of 8–63 printable ASCII characters or a 64-digit hexadecimal key.": "请输入 8–63 个可打印 ASCII 字符的 WPA2 密码，或 64 位十六进制密钥。",
}


def _translated(message, language):
    if language != "zh" or not message:
        return message
    if message in _ZH_MESSAGES:
        return _ZH_MESSAGES[message]
    patterns = (
        (r"^Update available: (.+) → (.+)\.$", "有可用更新：{0} → {1}。"),
        (r"^Update (.+) is available, but local changes block installation\.$",
         "更新 {0} 可用，但本地更改阻止了安装。"),
        (r"^Software is current at (.+)\. The checkout has local changes\.$",
         "软件已是最新版本 {0}，但代码目录有本地更改。"),
        (r"^Software is current at (.+)\.$", "软件已是最新版本：{0}。"),
        (r"^Updated to (.+)\. DigitalFrame is restarting now\.$",
         "已更新到 {0}。DigitalFrame 正在重启。"),
        (r"^Software is already current at (.+)\.$", "软件已经是最新版本：{0}。"),
    )
    for pattern, translated in patterns:
        match = re.match(pattern, message)
        if match:
            return translated.format(*match.groups())
    return message


def _folder_label(name, details, language):
    if details is None:
        return name
    date = details.updated.date().isoformat() if details.updated is not None else (
        "未知" if language == "zh" else "unknown"
    )
    if language == "zh":
        return f"{name} — {details.count} 张照片 — 更新于 {date}"
    noun = "picture" if details.count == 1 else "pictures"
    return f"{name} — {details.count} {noun} — updated {date}"


def render_page(current: int, *, submitted: str | None = None,
                error: str = "", status_code: int = 200,
                folders=(), selected_folder=None, issues=(), folder_details=None,
                months=(), selected_months=(), month_counts=None, view_mode="folder",
                wifi=DISABLED, wifi_token="", update=None, update_token="",
                language="en") -> HTMLResponse:
    language = "zh" if language == "zh" else "en"
    chinese = language == "zh"
    copy = _ZH if chinese else _EN
    folder_details = folder_details or {}
    month_counts = month_counts or {}
    active = (
        '<small aria-label="当前浏览模式">✓ 已启用</small>' if chinese
        else '<small aria-label="Active viewing mode">✓ Active</small>'
    )
    return HTMLResponse(
        _TEMPLATE.substitute(
            **copy,
            page_language="zh-Hans" if chinese else "en",
            toggle_language="en" if chinese else "zh",
            toggle_page_language="en" if chinese else "zh-Hans",
            toggle_label="English" if chinese else "中文",
            current_duration=(
                f"当前每张照片显示 {current} 秒。" if chinese
                else f"Current duration: {current} seconds per photo."
            ),
            value=escape(str(current) if submitted is None else submitted, quote=True),
            error=escape(_translated(error, language)),
            wifi_status=escape(_translated(wifi.message, language)),
            wifi_current=(
                f'<p>{"当前 Wi-Fi" if chinese else "Current Wi-Fi"}: {escape(wifi.ssid)}</p>'
                if wifi.ssid else ""
            ),
            wifi_options="".join(
                f'<option value="{escape(point["bssid"], quote=True)}"'
                f'{"" if point.get("supported") and wifi.state == "ap" else " disabled"}>'
                f'{escape(point["ssid"])} — {escape(point["bssid"])} — '
                f'{"信道" if chinese else "ch"} {point.get("channel") or "?"} — '
                f'{point.get("signal", "?")} dBm — '
                f'{escape(point.get("security", "未知" if chinese else "Unknown"))}</option>'
                for point in wifi.access_points
            ) or (
                '<option value="" disabled selected>未找到接入点；请使用下方的“刷新接入点”</option>'
                if chinese else
                '<option value="" disabled selected>No access points found; use Refresh access points below</option>'
            ),
            wifi_token=escape(wifi_token, quote=True),
            wifi_disabled="" if wifi.can_submit else " disabled",
            wifi_refresh_disabled="" if wifi.can_refresh else " disabled",
            wifi_readonly="" if wifi.can_submit else " readonly",
            update_status=escape(_translated(
                update.message if update is not None else "Updates have not been checked.", language
            )),
            update_token=escape(update_token, quote=True),
            update_form=(
                '<form method="post" action="/update/apply">'
                f'<input type="hidden" name="update_token" value="{escape(update_token, quote=True)}">'
                f'<button type="submit">{copy["install_update"]}</button></form>'
                if update is not None and update.can_apply else ""
            ),
            issues="".join(
                '<p style="color: red">'
                f'{escape(item["time"])} — {escape(item["source"])} '
                f'({"进行中" if item["active"] else "已恢复"}): '
                f'{escape(_translated(item["message"], language))}</p>'
                if chinese else
                '<p style="color: red">'
                f'{escape(item["time"])} — {escape(item["source"])} '
                f'({"active" if item["active"] else "recovered"}): '
                f'{escape(item["message"])}</p>'
                for item in issues
            ),
            folder_options="".join(
                f'<option value="{escape(value, quote=True)}"'
                f'{" selected" if value == (selected_folder or "") else ""}>'
                f'{escape(_folder_label(label, folder_details.get(value or None), language))}</option>'
                for value, label in [
                    ("", "全部" if chinese else "All"),
                    *((folder, folder) for folder in folders),
                ]
            ),
            folder_mode_check=active if view_mode == "folder" else "",
            month_mode_check=active if view_mode == "months" else "",
            month_options="".join(
                '<label>'
                f'<input type="checkbox" name="month" value="{escape(month, quote=True)}"'
                f'{" checked" if month in selected_months else ""}>'
                f'{escape(photo_month_label(month))} — '
                + (f'{month_counts.get(month, 0)} 张照片' if chinese else
                   f'{month_counts.get(month, 0)} '
                   f'{"picture" if month_counts.get(month, 0) == 1 else "pictures"}')
                + '</label><br>'
                for month in months
            ) or (
                "<p>目前没有可用的带日期照片月份。</p>" if chinese
                else "<p>No dated photo months are available yet.</p>"
            ),
        ),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )
