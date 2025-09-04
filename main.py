import pytz
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from utils import *

app = FastAPI()
processed_events = set()


@app.on_event("startup")
async def startup_event():
    print("🚀 Starting FastAPI + Scheduler")
    tz = pytz.timezone("Asia/Karachi")

    # Mon–Thu → reminder 6 PM
    scheduler.add_job(
        send_daily_messages,
        trigger="cron",
        day_of_week="mon-thu",
        hour=20, minute=35,
        timezone=tz
    )

    # Friday → reminder 1 PM
    scheduler.add_job(
        send_daily_messages,
        trigger="cron",
        day_of_week="fri",
        hour=16, minute=12,
        timezone=tz
    )
    scheduler.start()


@app.get("/")
async def home():
    return {"message": "Slack bot running ✅"}


@app.post("/slack/events")
async def slack_events(req: Request):
    data = await req.json()

    # Slack verification challenge
    if data.get("type") == "url_verification":
        return JSONResponse(content={"challenge": data["challenge"]})

    if "event" in data:
        event_id = data.get("event_id")
        event = data["event"]

        # 🔑 prevent duplicate processing
        if event_id in processed_events:
            return {"ok": True}
        processed_events.add(event_id)

        # ignore bot/system messages
        if event.get("subtype") in ["bot_message", "message_changed", "message_deleted"]:
            return JSONResponse(content={"ok": True})

        user = event.get("user")
        text = event.get("text")

        # ✅ Check if audio file attached
        files = event.get("files", [])
        audio_file_path = None
        if files:
            for file in files:
                if file.get("mimetype", "").startswith("audio/"):
                    file_url = file["url_private_download"]
                    file_name = f"./tmp/{file['id']}.m4a"
                    audio_file_path = file_name

                    # Download audio
                    downloaded = await download_file(file_url, file_name)
                    if downloaded:
                        # Convert to text
                        text = await transcribe_audio(downloaded)
                        print(f"🎙️ Transcribed audio: {text}")

        # Slack user info
        user_info = await client.users_info(user=user)
        email = user_info["user"]["profile"].get("email")

        if text and email:
            # ✅ Employee record fetch
            employee = get_employee_by_email(email)
            if not employee:
                print(f"⚠️ No employee found for email: {email}")
                return JSONResponse(content={"ok": True})

            name = employee["name"]
            domain = employee["domain"]

            # ✅ Run chatbot
            structured_reply = await run_chatbot(text)

            # ✅ Find Slack channel by domain
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
