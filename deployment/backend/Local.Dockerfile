# Reuse the fully compiled original NGOPilot Agent and isolated algorithm venvs.
ARG AGENT_BASE=ngopilot-takeover:local
FROM ${AGENT_BASE}
COPY MCPcode/src/ngopilot_mcp /opt/ngopilot/mcp/ngopilot_mcp
COPY deployment/backend/ngopilot_gateway /opt/ngopilot/gateway/ngopilot_gateway
COPY deployment/frontend/dist /opt/ngopilot/frontend
COPY deployment/agent-samples /opt/ngopilot/agent-samples
ENV PYTHONPATH=/opt/ngopilot/gateway:/opt/ngopilot/mcp \
    APP_ENV=local \
    NGOPILOT_FRONTEND_DIR=/opt/ngopilot/frontend
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request,urllib.parse; origin=os.getenv('PUBLIC_API_URL','http://127.0.0.1:8310'); req=urllib.request.Request('http://127.0.0.1:'+os.getenv('PORT','8310')+'/healthz',headers={'Host':urllib.parse.urlsplit(origin).netloc}); urllib.request.urlopen(req,timeout=4)" || exit 1
CMD ["python", "-m", "ngopilot_gateway.local_run", "--env-file", "/run/ngopilot-provider.env"]
