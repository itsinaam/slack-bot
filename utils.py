from langchain_core.messages import HumanMessage, SystemMessage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from datetime import datetime
import aiohttp
import os
import pytz
from datetime import timedelta
tz = pytz.timezone("Asia/Karachi")

load_dotenv()

# Fake in-memory DB for updates
employee_updates = {}

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")

client = AsyncWebClient(token=SLACK_BOT_TOKEN)

scheduler = AsyncIOScheduler()

INITIAL_MESSAGE = """
   👋 Hello! This is your friendly Slack Assistant Bot.  
I'll remind you to provide your Eli Executive level status updates in this Slack-bot!  
🎙️ You can also send me a voice note :studio_microphone: or text, and I'll transcribe them into the text format.  
❓ If you have any questions, just message me here!  
✨ Remember this is high level activities.  

🚀 Let's stay productive together!  

📊 Weekly Status Report  
🗣️ Please send a voice note with your weekly update.  
I'll automatically transcribe and format it into the sections below.  

📝 **Summary of the Week's Activities**  
[Your summary here]  

✅ **Activities Completed (Since last update)**  
- [Activity 1]  
- [Activity 2]  
- [Activity 3]  
- [Activity 4]  
- [Activity 5]  

🛠️ **Activities to be Worked On (before next update)**  
- [Activity 1]  
- [Activity 2]  
- [Activity 3]  
- [Activity 4]  
- [Activity 5]  

❓ **Questions for Eli / Stuck Items**  
(💡 You can also mention Scott and I'll try to resolve it.)  
- [Question or stuck item 1]  
- [Question or stuck item 2]  
- [Question or stuck item 3]  
- [Question or stuck item 4]  
- [Question or stuck item 5]  

"""

raw_data = [
    ("muhammadjunaidakhter100@gmail.com", "M. Junaid", "testing-executive-updates")
]

def record_employee_update(email: str):
    """Mark that an employee submitted an update now."""
    employee_updates[email] = {"last_update": datetime.now()}
    print(f"✅ Update recorded for {email}")



def get_all_employees():
    """Return all employees as list of dicts (full records)."""
    employees = [
        {"email": email, "name": name, "domain": domain}
        for email, name, domain in raw_data
    ]
    return employees

def get_all_emails():
    """Return only employee emails as list of dicts."""
    emails = [{"email": email} for email, _, _ in raw_data]
    return emails

async def send_followup_reminder(day: str):
    print(f"⏰ Checking follow-up reminders for {day}...")
    now = datetime.now(tz)

    for emp in get_all_employees():
        email = emp["email"]
        name = emp["name"]

        last_update = employee_updates.get(email, {}).get("last_update")

        # Agar update missing hai ya due ke baad aya hai → send reminder
        if not last_update or last_update < now - timedelta(hours=1):
            await dm_by_email(
                email,
                f"⚠️ Hey {name}, we did not receive your update for {day}. "
                "Please provide it as soon as possible."
            )

async def send_daily_messages():
    print("⏰ Sending daily messages...")
    emails = get_all_emails()
    for email in emails:
        await dm_by_email(email["email"], INITIAL_MESSAGE)
        
async def run_chatbot(text: str,) -> str:
    model = ChatOpenAI(
        model="gpt-4o",
        temperature=0.3,
    )

    messages = [
        SystemMessage(content="""
        You are a helpful assistant.
        Your task is to take user input and rewrite it in a clear executive update format.

        The format must follow this structure:

        📝 Summary of the Week's Activities
            <one short paragraph summary>

        ✅ Activities Completed (Since last update)
                        • <task 1>  
                        • <task 2>  
                        • <task 3>  
                        ...

        🛠️ Activities to be Worked On (before next update) 
        • <milestone 1>  
        • <milestone 2>  
        ...

        ❓ Questions for Eli / Stuck Items  
    (💡 You can also mention Scott and I'll try to resolve it.)  
                        • <question 1>  
                        • <question 2>  
                        ...

        Rules:
        - Keep section headings exactly as shown above with emojis.
        - Use bullet points (•) for lists.
        - Keep tone professional and concise.
        - If a section has no content, still include the heading but leave it blank.
        - Use emojis only in headings, not in the list items.
        """)

        ,

        HumanMessage(content=text)
    ]

    response = await model.ainvoke(messages)

    return response.content

async def download_file(file_url: str, file_name: str):
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url, headers=headers) as resp:
            if resp.status == 200:
                with open(file_name, "wb") as f:
                    f.write(await resp.read())
                return file_name
            else:
                print(f"⚠️ Failed to download file {file_url}, status={resp.status}")
                return None

async def transcribe_audio(file_path: str) -> str:
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY")

    with open(file_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    return transcript.text

def get_employee_by_email(email: str):
    employees = get_all_employees()
    for emp in employees:
        if emp["email"] == email:
            return emp
    return None

async def get_channel_id(channel_name: str) -> str:
    try:
        all_channels = []

        # Fetch first batch
        result = await client.conversations_list(types="public_channel,private_channel")
        all_channels.extend(result["channels"])

        # Handle pagination
        while result.get("response_metadata", {}).get("next_cursor"):
            cursor = result["response_metadata"]["next_cursor"]
            result = await client.conversations_list(
                types="public_channel,private_channel",
                cursor=cursor
            )
            all_channels.extend(result["channels"])

        # Search channel by name
        for channel in all_channels:
            if channel["name"] == channel_name:
                return channel["id"]

        return f"Channel '{channel_name}' does not exist in this workspace."

    except SlackApiError as e:
        return f"Error: {e.response['error']}"

async def dm_by_email(email: str, text: str):
    try:
        u = await client.users_lookupByEmail(email=email)
        user_id = u["user"]["id"]

        im = await client.conversations_open(users=[user_id])
        channel_id = im["channel"]["id"]

        await client.chat_postMessage(channel=channel_id, text=text)
    except SlackApiError as e:
        print("Slack error:", e.response.get("error"))








