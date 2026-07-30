from src.agent import create_delivery_support_agent, load_environment
from agent_framework_foundry_hosting import ResponsesHostServer

load_environment()

agent = create_delivery_support_agent()
app = ResponsesHostServer(agent=agent)

if __name__ == "__main__":
    app.run()
