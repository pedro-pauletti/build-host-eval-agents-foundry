# Publishing the InventoryAgent to Microsoft Teams

Foundry can surface a **prompt agent** inside **Microsoft Teams**. Because this creates an **Azure Bot** and
a **Microsoft 365 app** and requires **tenant admin consent**, activation is a guided/manual step (it can't
be fully scripted without M365 admin rights). This is the last-mile activation the demo leaves to you.

## Prerequisites
- The `InventoryAgent` exists in the Foundry project (created by `agents/inventory-agent/create_agent.py`).
- You (or an admin) can grant **admin consent** in the Microsoft 365 tenant.
- A Teams team/channel where you can side-load or install the app.

## Steps (Foundry portal)
1. Go to the [Foundry portal](https://ai.azure.com) → your project (`zava-project`) → **Agents** → **InventoryAgent**.
2. Open **Channels / Publish** → choose **Microsoft Teams**.
3. Foundry provisions an **Azure Bot** resource and registers a **Teams app** (an M365 app manifest).
   Approve the creation.
4. **Grant admin consent** for the app's Graph/Bot permissions (Microsoft 365 admin center → Enterprise
   applications, or the consent prompt shown during publish).
5. Download the generated **Teams app package** (`.zip`) and **upload it to Teams**
   (Teams → Apps → Manage your apps → Upload a custom app) for your team, or publish it to your org's app
   catalog.
6. Open the app in Teams and chat: *"What are my most critical stock issues right now?"*

## Notes & limitations
- **MCP identity passthrough is not supported in Teams.** When the agent calls the Zava MCP tools from Teams,
  it uses the **project managed identity** (not the signed-in Teams user's identity). That is fine here — the
  Zava tools authorize at the service level, not per end-user.
- The bot honors the same agent instructions and tools (KB + MCP) configured in `create_agent.py`.
- To remove the Teams integration later, delete the Azure Bot resource and remove the app from Teams; the
  demo `scripts/teardown.ps1` deletes `rg-zava-demo` but does **not** remove a separately-created Bot/M365 app.

## Reference
- Foundry → Teams channel: https://learn.microsoft.com/azure/ai-foundry/agents/how-to/use-agent-in-teams
