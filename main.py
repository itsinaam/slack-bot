import pytz
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from utils import *

app = FastAPI()
processed_events = set()

@app.get("/")
async def home():
    return {"message": "Slack bot running ✅"}

# 🔹 Trigger route for daily reminders (Wed/Fri)
@app.api_route("/trigger/daily-messages", methods=["GET", "POST"])
async def trigger_daily_messages():
    await send_daily_messages()
    return {"status": "ok", "trigger": "daily-messages"}

# 🔹 Trigger route for follow-up reminders (Tue/Sat)
@app.post("/trigger/followup/{day}")
async def trigger_followup(day: str):
    await send_followup_reminder(day)
    return {"status": "ok", "trigger": f"followup-{day}"}

# 🔹 Slack events webhook
@app.post("/slack/events")
async def slack_events(req: Request):
    data = await req.json()

    # Slack verification challenge
    if data.get("type") == "url_verification":
        return JSONResponse(content={"challenge": data["challenge"]})

    if "event" in data:
        event = data["event"]

        # 🔑 Deduplication key (client_msg_id if present, otherwise timestamp)
        msg_id = event.get("client_msg_id") or event.get("ts")
        if msg_id in processed_events:
            return {"ok": True}
        processed_events.add(msg_id)

        # 🚫 Ignore system/bot updates
        if event.get("subtype") in ["bot_message", "message_changed", "message_deleted"]:
            return JSONResponse(content={"ok": True})

        user = event.get("user")
        text = event.get("text")

        # ✅ Handle audio file uploads
        files = event.get("files", [])
        audio_file_path = None
        if files:
            for file in files:
                if file.get("mimetype", "").startswith("audio/"):
                    file_url = file["url_private_download"]
                    file_name = f"{file['id']}.m4a"
                    audio_file_path = file_name

                    downloaded = await download_file(file_url, file_name)
                    if downloaded:
                        text = await transcribe_audio(downloaded)
                        print(f"🎙️ Transcribed audio: {text}")

        # 🔎 Get Slack user info
        user_info = await client.users_info(user=user)
        email = user_info["user"]["profile"].get("email")

        if text and email:
            employee = get_employee_by_email(email)
            if not employee:
                print(f"⚠️ No employee found for email: {email}")
                return JSONResponse(content={"ok": True})

            name = employee["name"]
            domain = employee["domain"]

            structured_reply = await run_chatbot(text)
            record_employee_update(email)

            channel_id = await get_channel_id(domain)
            if channel_id:
                await client.chat_postMessage(
                    channel=channel_id,
                    text=f"*Message from {name} ({email}):*\n```{structured_reply}```"
                )

                if audio_file_path and os.path.exists(audio_file_path):
                    os.remove(audio_file_path)
                    print(f"🗑️ Deleted file: {audio_file_path}")
            else:
                print(f"⚠️ No channel found for domain: {domain}")

    return JSONResponse(content={"ok": True})

