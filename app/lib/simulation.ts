import { Agent, Source, SimStep } from "./types";
import { uuid, timestamp } from "./utils";

// TODO: wire real simulation engine — _prompt is currently ignored; steps are hardcoded by agent count
export function generateSimSteps(
  agents: Agent[],
  sources: Source[],
  _prompt: string,
): SimStep[] {
  if (agents.length === 0) return [];

  const steps: SimStep[] = [];
  const ts = () => timestamp();

  steps.push({
    id: uuid(),
    ts: ts(),
    label: "SYSTEM",
    msg: "Prompt received — broadcasting to all agents",
    type: "system",
  });

  if (agents.length >= 2) {
    steps.push({
      id: uuid(),
      ts: ts(),
      label: agents[0].name,
      target: agents[1].name,
      msg: "sharing initial analysis",
      type: "agent-to-agent",
      fromId: agents[0].id,
      toId: agents[1].id,
    });
  }

  if (agents.length >= 2) {
    const toolAgent = agents[1];
    steps.push({
      id: uuid(),
      ts: ts(),
      label: toolAgent.name,
      msg:
        toolAgent.tools.length > 0
          ? `accessing tool [${toolAgent.tools[0]}]`
          : "processing initial analysis",
      type: "tool",
      nodeId: toolAgent.id,
    });
  }

  if (agents.length >= 1 && sources.length >= 1) {
    const reader = agents[agents.length >= 3 ? 2 : 0];
    steps.push({
      id: uuid(),
      ts: ts(),
      label: reader.name,
      target: sources[0].name,
      msg: "reading document",
      type: "agent-to-source",
      fromId: reader.id,
      toId: sources[0].id,
    });
  }

  if (agents.length >= 3) {
    steps.push({
      id: uuid(),
      ts: ts(),
      label: agents[0].name,
      target: agents[2].name,
      msg: "proposing finding",
      type: "agent-to-agent",
      fromId: agents[0].id,
      toId: agents[2].id,
    });
    steps.push({
      id: uuid(),
      ts: ts(),
      label: agents[2].name,
      msg: "counter-proposal posted",
      type: "tool",
      nodeId: agents[2].id,
    });
  } else if (agents.length >= 2) {
    steps.push({
      id: uuid(),
      ts: ts(),
      label: agents[0].name,
      target: agents[1].name,
      msg: "proposing finding",
      type: "agent-to-agent",
      fromId: agents[0].id,
      toId: agents[1].id,
    });
  }

  if (agents.length >= 2) {
    steps.push({
      id: uuid(),
      ts: ts(),
      label: agents[1].name,
      target: agents[0].name,
      msg: "supporting position",
      type: "agent-to-agent",
      fromId: agents[1].id,
      toId: agents[0].id,
    });
  }

  if (agents.length >= 3) {
    steps.push({
      id: uuid(),
      ts: ts(),
      label: agents[0].name,
      target: agents[2].name,
      msg: "defense argument posted",
      type: "agent-to-agent",
      fromId: agents[0].id,
      toId: agents[2].id,
    });
    steps.push({
      id: uuid(),
      ts: ts(),
      label: agents[1].name,
      target: agents[2].name,
      msg: `voting — support ${agents[0].name}`,
      type: "agent-to-agent",
      fromId: agents[1].id,
      toId: agents[2].id,
    });
  }

  steps.push({
    id: uuid(),
    ts: ts(),
    label: "SYSTEM",
    msg: `Consensus reached — ${agents[0].name} finding confirmed`,
    type: "system",
  });
  steps.push({
    id: uuid(),
    ts: ts(),
    label: "SYSTEM",
    msg: "Output ready",
    type: "system",
  });

  return steps;
}
