import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import json
import anthropic
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_core.output_parsers import PydanticOutputParser
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from google import genai
from google.genai import types
import base64
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from twilio.rest import Client
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # or list of allowed domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserInput(BaseModel):
    query: str

google_key = os.getenv("GOOGLE_API_KEY")
account_sid = os.getenv("ACCOUNT_SID")
auth_token= os.getenv("AUTH_TOKEN")
google_client = genai.Client(api_key=google_key)
twilio_client = Client(account_sid, auth_token)
llm = ChatGoogleGenerativeAI(google_api_key= google_key, model="gemini-3-pro-preview", temperature=0.2)
mcp_client = MultiServerMCPClient(
        {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "transport": "stdio",
            "env": {
                "GITHUB_PERSONAL_ACCESS_TOKEN": os.getenv("GITHUB_TOKEN"),
            },
        }
    },)


creative_agent_prompt = """
# ROLE
You are the Creative Engineering Agent — an autonomous technical reasoning system that intelligently decides how to modify code and generate high-quality visuals.

# SPECIALIZATIONS
- Updating and modifying repository files safely and precisely.
- Identifying improvement opportunities and proposing structured changes.
- Generating visual assets such as diagrams, UI concepts, and technical illustrations.

# AVAILABLE TOOLS
- `github_write_file` → Update existing files in a GitHub repository using safe, controlled writes with commit messages.
- `graphical_visual_generation` → Generate high-quality conceptual or technical images from natural language prompts.

# DEFAULT ASSUMPTIONS
If the user references a repository without specifying the owner, assume:
owner = "keemstarr123"

# AGENT RESPONSIBILITIES
- Understand user intent and autonomously decide when a tool call is required.
- Before modifying code, clearly explain the intended change and rationale unless the user explicitly requests direct execution.
- Maintain safety: never delete entire files or produce destructive changes.
- Produce clean, high-quality results that maintain architectural integrity and usability.
- Generate diagrams or visuals when they clarify or enhance the requested solution.

# RESPONSE RULES
- Think step-by-step internally but **do not reveal reasoning or internal chain-of-thought**.
- When a tool call is needed, return only the required tool invocation in the correct format.
- When no tool call is required, respond naturally, clearly, and professionally.

# DECISION POLICY
- Code modification → propose update and/or execute via `github_write_file`.
- Visual or creative conceptualization → call `graphical_visual_generation`.

# BEHAVIOR PRINCIPLES
- Act proactively and strategically.
- Favor minimal, precise, high-impact updates.
- Maintain clarity, correctness, and safety across all actions.

You are reliable, intelligent, and capable of transforming ideas into clean technical implementations and engaging creative visuals.
"""




USERNAME = "keemstarr123"

REPOS = ['lucky-draw', 'activity_gallery']

async def _read_recursive(session, owner, repo, path, branch, outputs):
    tools = await load_mcp_tools(session, server_name="github")
    get_file_contents = next(t for t in tools if t.name.endswith("get_file_contents"))

    listing = await get_file_contents.ainvoke(
        {"owner": owner, "repo": repo, "path": path, "branch": branch}
    )
    items = json.loads(listing)

    for item in items:
        name = item["name"]
        fp = f"{path}/{name}".lstrip("/")
        if item["type"] == "dir":
            await _read_recursive(session, owner, repo, fp, branch, outputs)
        else:
            content = await get_file_contents.ainvoke(
                {"owner": owner, "repo": repo, "path": fp, "branch": branch}
            )
            outputs[fp] = content

async def github_read_file(owner: str, repo: str, path: str, branch: str = "main"):
    async with mcp_client.session("github") as session:
        result = await session.call_tool(
            "get_file_contents",
            {"owner": owner, "repo": repo, "path": path, "ref": branch},
        )
        return result


import json
import base64
import re

async def _write_file(session, owner, repo, path, content, message, branch):
    tools = await load_mcp_tools(session, server_name="github")
    get_file_contents = next(t for t in tools if t.name == "get_file_contents")
    write_file = next(t for t in tools if t.name == "create_or_update_file")

    # 1) Read file via MCP
    tool_result = await get_file_contents.ainvoke(
        {"owner": owner, "repo": repo, "path": path, "ref": branch}
    )
    json_text = json.loads(tool_result)
    print(json_text)
    file_data = json_text['content']

    sha = json_text["sha"]

    # 2) Replace PRIZES block
    new_prizes_block = f"""export const PRIZES: Prize[] = {content};"""

    updated_ts = re.sub(
        r"export const PRIZES: Prize\[\][\s\S]*?];",
        new_prizes_block,
        file_data,
    )

    # 3) Encode for GitHub API
    encoded = base64.b64encode(updated_ts.encode("utf-8")).decode("utf-8")

    # 4) Write file back
    await write_file.ainvoke(
        {
            "owner": owner,
            "repo": repo,
            "path": path,
            "branch": branch,
            "content": updated_ts,
            "sha": sha,
            "message": message,
        }
    )
    



#
# PUBLIC LangChain tools — agent will call these
#


@tool("github_write_file")
def github_write_file( content: str = "", message: str = ""):
    """
    Update the PRIZES array within the constants.ts file in the target GitHub repository.

    PURPOSE:
    Use this tool to overwrite the current `export const PRIZES: Prize[] = [...]` block
    in `constants.ts` with a new list of prize objects.

    REQUIRED INPUTS:
    - `content`: A JavaScript array representing the PRIZES list.
    - `message`: A Git commit message that describes the update.

    IMPORTANT FORMAT RULES:
    - The `content` must be an array of at least **7** Prize objects.
    - Each object must include: `id`, `name`, `image`, `color`, and `rarity`.
    - The input should only contain the array (not the entire file).
    - The tool will automatically replace the existing PRIZES block.

    Example valid `content` structure (7 items required, values may vary):
    [
      {
        id: '1',
        name: 'Uni5G Unlimited Data Pass',
        image: 'https://example.com/data.jpg',
        color: 'from-pink-500 to-pink-900',
        rarity: 'Legendary'
      },
      {
        id: '2',
        name: 'Apple AirPods Pro',
        image: 'https://example.com/airpods.jpg',
        color: 'from-white to-gray-700',
        rarity: 'Epic'
      },
      {
        id: '3',
        name: 'Dyson Supersonic Hair Dryer',
        image: 'https://example.com/dyson.jpg',
        color: 'from-purple-600 to-pink-700',
        rarity: 'Epic'
      },
      {
        id: '4',
        name: 'Starbucks RM50 Gift Card',
        image: 'https://example.com/starbucks.jpg',
        color: 'from-green-600 to-emerald-800',
        rarity: 'Rare'
      },
      {
        id: '5',
        name: 'Portable Power Bank 20000mAh',
        image: 'https://example.com/powerbank.jpg',
        color: 'from-slate-600 to-slate-900',
        rarity: 'Common'
      },
      {
        id: '6',
        name: 'Bluetooth Speaker',
        image: 'https://example.com/speaker.jpg',
        color: 'from-orange-500 to-red-700',
        rarity: 'Common'
      },
      {
        id: '7',
        name: 'Lucky Mystery Box',
        image: 'https://example.com/mystery.jpg',
        color: 'from-yellow-300 to-amber-600',
        rarity: 'Legendary'
      }
    ]

    BEHAVIOR:
    - Automatically locates and replaces the PRIZES list via regex.
    - Any other part of the file remains unchanged.
    - `message` becomes the Git commit note in GitHub.
    """
    owner = "keemstarr123"
    repo= "lucky-draw"
    path: str = "constants.ts"
    branch: str = "main"
    async def run():
        async with mcp_client.session("github") as session:
            await _write_file(session, owner, repo, path, content, message, branch)
        return {"status": "ok"}

    # Tool itself is sync, so we drive the async part here
    return asyncio.run(run())

    
@tool("github_all_read_files")
def github_all_read_files(
    owner: str,
    repo: str,
    path: str = "",
    branch: str = "main",
) -> str:
    """Recursively read all files from a GitHub repo using MCP."""
    outputs = {}

    async def run():
        async with mcp_client.session("github") as session:
            await _read_recursive(session, owner, repo, path, branch, outputs)
        return json.dumps(outputs)

    return asyncio.run(run())


@tool("graphical_visual_generation")
def graphical_visual_generation(
    prompt:str,
    aspect_ratio = "1:1", # "1:1","2:3","3:2","3:4","4:3","4:5","5:4","9:16","16:9","21:9"
    ):
    """
    Generates a high-quality visual asset using the Gemini 3 Pro Image Preview model.

    This tool:
    - Uses the `gemini-3-pro-image-preview` image generation model to create a visual
      based on a natural language prompt.
    - Supports multiple aspect ratios (for example "1:1", "16:9", "9:16") and produces
      a 1K-resolution image suitable for presentations, marketing materials, UI mockups,
      infographics, and other graphical assets.
    - Can return both image and optional text commentary from the model, such as
      descriptions or design notes.
    - Saves the generated image to disk as a PNG file (e.g. "butterfly.png") in the
      current working directory.

    Useful for:
    - Quickly prototyping posters, logos, infographics, and hero images.
    - Creating visual concepts for campaigns, decks, or UI layouts from a text brief.
    - Generating illustrative assets that match a specific style, mood, or composition.
    - Producing social-media or slideshow graphics with a precise aspect ratio.

    Args:
        prompt (str): A detailed natural language description of the desired image.
            The best results come from specifying subject, style, mood, composition,
            and any important text or branding to include.
        aspect_ratio (str, optional): The desired aspect ratio of the output image.
            Must be one of: "1:1", "2:3", "3:2", "3:4", "4:3", "4:5",
            "5:4", "9:16", "16:9", or "21:9".
            Defaults to "1:1".

    Returns:
        None: The function prints any textual response from the model and saves the
        generated image as a PNG file in the current working directory.
    """
    chat = google_client.chats.create(
    model="gemini-3-pro-image-preview",
    config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
        tools=[{"google_search": {}}],
        image_config=types.ImageConfig(
            aspect_ratio=aspect_ratio,
        )
    )
    )
    
    response = chat.send_message(prompt)

    for part in response.parts:
        if part.text is not None:
            print(part.text)
        elif image:= part.as_image():
            image.save("photosynthesis.png")


@tool("send_whatsapp")
def send_whatsapp(link:str):
    """
    Description:
        Sends a WhatsApp message using Twilio's WhatsApp API.
        This tool triggers a pre-approved WhatsApp template message
        identified by a Content SID.

    Arguments:
        link (str): A parameter intended for passing additional context 
                    or URLs to include dynamically in the template message.
                    (Currently unused in this snippet, but reserved for expansion).

    Behavior:
        - Uses Twilio messaging service to send a WhatsApp template message
        to a predefined recipient number.
        - Injects template variables into the message (e.g., recipient name).
        - Prints message status and the Twilio Message SID upon success.

    Returns:
        None
    """
    link = "https://lucky-draw-snowy.vercel.app/" if link != "https://lucky-draw-snowy.vercel.app/" else link

    message = twilio_client.messages.create(
        content_sid="HX4f99487d6dbd00b49399d9f76f49188b",
        from_="whatsapp:+19893316241",  # <-- Your Messaging Service SID (recommended)
        to="whatsapp:+601156388248",                         # <-- Receiver phone number
        content_variables=json.dumps({"1": "Vishnu"}) # change to link when approved   
    )

    print("Message sent!")
    print("SID:", message.sid)



                
Creative_Agent = create_agent(
    llm,
    tools=[github_write_file, graphical_visual_generation],
    system_prompt = creative_agent_prompt,
)

Media_Agent = create_agent(
    llm,
    tools=[],
    system_prompt="Hello"
)


@app.post("/creative")
def creative_agent_interaction(prompt: UserInput):
    result = Creative_Agent.invoke(
                    {
                        "messages": [{
                            "role": "user",
                            "content": (
                                prompt                            
                            )
                        }]
                    },
                    config={"recursion_limit": 25},
                )["messages"][-1]
    return result 

@app.post("/media")
def creative_agent_interaction(prompt: UserInput):
    result = Media_Agent.invoke(
                    {
                        "messages": [{
                            "role": "user",
                            "content": (
                                "Trigger the Whatsapp send"
                            )
                        }]
                    },
                    config={"recursion_limit": 25},
                )["messages"][-1]
    return result 




"""
# List Anthropic-managed Skills
skills = client.beta.skills.list(
    source="anthropic",
    betas=["skills-2025-10-02"]
)

for skill in skills.data:
    print(f"{skill.id}: {skill.display_title}")

"""

