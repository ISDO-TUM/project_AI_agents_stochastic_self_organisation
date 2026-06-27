"use client";

import { useReducer, useEffect, useCallback } from "react";
import {
  CanvasState,
  CanvasAction,
  Agent,
  Edge,
  Source,
  SourceType,
} from "@/lib/types";
import { uuid, autoLayout } from "@/lib/utils";
import {
  fetchAgents,
  fetchFiles,
  fetchAgentFiles,
  createAgent,
  updateAgent,
  deleteAgentApi,
  createFile,
  updateFileContent,
  deleteFileApi,
  attachFile,
  detachFile,
  patchAgentTools,
} from "@/lib/api";

// The backend stores knowledge files as plain (id, name, content) rows — it has
// no notion of "dataset" vs "text". We infer it from the file extension so a
// reloaded CSV still gets the dataset UI (type select, CSV preview, etc.)
// instead of silently reverting to "text" and losing its preview.
function inferSourceType(name: string): SourceType {
  return /\.(csv|tsv)$/i.test(name) ? "dataset" : "text";
}

/** Backend tool name(s) a source of this type should grant its attached agents. */
function capabilityToolsFor(type: SourceType): string[] {
  return type === "dataset" ? ["table_query", "table_mutate"] : ["files"];
}

function reducer(state: CanvasState, action: CanvasAction): CanvasState {
  const { agents, sources, edges } = state;
  switch (action.type) {
    case "ADD_AGENT":
      return { ...state, agents: [...agents, action.agent] };
    case "UPDATE_AGENT":
      return {
        ...state,
        agents: agents.map((a) =>
          a.id === action.agent.id ? action.agent : a,
        ),
      };
    case "DELETE_AGENT":
      return {
        ...state,
        agents: agents
          .filter((a) => a.id !== action.id)
          .map((a) => ({
            ...a,
            connections: a.connections.filter((c) => c !== action.id),
          })),
        edges: edges.filter((e) => e.from !== action.id && e.to !== action.id),
      };
    case "ADD_SOURCE":
      return { ...state, sources: [...sources, action.source] };
    case "UPDATE_SOURCE":
      return {
        ...state,
        sources: sources.map((s) =>
          s.id === action.source.id ? action.source : s,
        ),
      };
    case "DELETE_SOURCE":
      return {
        ...state,
        sources: sources.filter((s) => s.id !== action.id),
        edges: edges.filter((e) => e.from !== action.id && e.to !== action.id),
      };
    case "MOVE_NODE":
      return {
        ...state,
        agents: agents.map((a) =>
          a.id === action.id ? { ...a, position: action.position } : a,
        ),
        sources: sources.map((s) =>
          s.id === action.id ? { ...s, position: action.position } : s,
        ),
      };
    case "ADD_EDGE":
      return edges.some(
        (e) => e.from === action.edge.from && e.to === action.edge.to,
      )
        ? state
        : { ...state, edges: [...edges, action.edge] };
    case "DELETE_EDGE":
      return { ...state, edges: edges.filter((e) => e.id !== action.id) };
    case "CLEAR":
      return { agents: [], sources: [], edges: [] };
    case "LOAD":
      return action.state;
    case "AUTO_LAYOUT": {
      const { agents: na, sources: ns } = autoLayout(agents, sources);
      return { ...state, agents: na, sources: ns };
    }
    default:
      return state;
  }
}

export function useCanvasState() {
  const [state, dispatch] = useReducer(reducer, {
    agents: [],
    sources: [],
    edges: [],
  });
  const { agents, sources, edges } = state;

  useEffect(() => {
    async function load() {
      const [agentList, fileList] = await Promise.all([
        fetchAgents(),
        fetchFiles(),
      ]);

      // Fetch each agent's attached files in parallel to build agent→file edges.
      const agentFileIds = await Promise.all(
        agentList.map(async (agent) => {
          const files = await fetchAgentFiles(agent.id);
          return { agentId: agent.id, fileIds: files.map((f) => f.id) };
        }),
      );

      const sources: Source[] = fileList.map((f, i) => ({
        id: f.id,
        name: f.name,
        type: inferSourceType(f.name),
        content: f.content,
        position: {
          x: 180 + (i % 4) * 220,
          y: 480 + Math.floor(i / 4) * 180,
        },
      }));

      const fileIdSet = new Set(fileList.map((f) => f.id));

      // Agent→agent edges from stored connections.
      const agentEdges: Edge[] = agentList.flatMap((a) =>
        a.connections
          .filter((toId) => agentList.some((b) => b.id === toId))
          .map((toId) => ({ id: uuid(), from: a.id, to: toId })),
      );

      // Agent→file edges from the agent_files join table.
      const fileEdges: Edge[] = agentFileIds.flatMap(({ agentId, fileIds }) =>
        fileIds
          .filter((fid) => fileIdSet.has(fid))
          .map((fid) => ({ id: uuid(), from: agentId, to: fid })),
      );

      dispatch({
        type: "LOAD",
        state: {
          agents: agentList,
          sources,
          edges: [...agentEdges, ...fileEdges],
        },
      });
    }

    load().catch(() => {});
  }, []);

  const saveAgent = useCallback(
    async (data: Agent) => {
      const exists = agents.find((a) => a.id === data.id);
      try {
        const saved = exists
          ? await updateAgent(data)
          : await createAgent(data);
        const withPos: Agent = { ...saved, position: data.position };
        if (exists) {
          dispatch({ type: "UPDATE_AGENT", agent: withPos });
          const existing = edges
            .filter((e) => e.from === data.id)
            .map((e) => e.to);
          withPos.connections
            .filter((c) => !existing.includes(c))
            .forEach((toId) =>
              dispatch({
                type: "ADD_EDGE",
                edge: { id: uuid(), from: withPos.id, to: toId },
              }),
            );
        } else {
          dispatch({ type: "ADD_AGENT", agent: withPos });
          withPos.connections.forEach((toId) =>
            dispatch({
              type: "ADD_EDGE",
              edge: { id: uuid(), from: withPos.id, to: toId },
            }),
          );
        }
      } catch {
        if (exists) {
          dispatch({ type: "UPDATE_AGENT", agent: data });
          const existing = edges
            .filter((e) => e.from === data.id)
            .map((e) => e.to);
          data.connections
            .filter((c) => !existing.includes(c))
            .forEach((toId) =>
              dispatch({
                type: "ADD_EDGE",
                edge: { id: uuid(), from: data.id, to: toId },
              }),
            );
        } else {
          dispatch({ type: "ADD_AGENT", agent: data });
          data.connections.forEach((toId) =>
            dispatch({
              type: "ADD_EDGE",
              edge: { id: uuid(), from: data.id, to: toId },
            }),
          );
        }
      }
    },
    [agents, edges],
  );

  const deleteAgent = useCallback(async (id: string) => {
    try {
      await deleteAgentApi(id);
    } catch {
      // API unavailable — proceed with local delete
    }
    dispatch({ type: "DELETE_AGENT", id });
  }, []);

  const deleteEdge = useCallback(
    (id: string) => {
      const e = edges.find((edge) => edge.id === id);
      if (e) {
        const agFrom = agents.find((a) => a.id === e.from);
        const agTo = agents.find((a) => a.id === e.to);
        const srcFrom = sources.find((s) => s.id === e.from);
        const srcTo = sources.find((s) => s.id === e.to);

        // agent→agent: remove from both agents' connection lists
        if (agFrom && agTo) {
          const updatedFrom = {
            ...agFrom,
            connections: agFrom.connections.filter((c) => c !== agTo.id),
          };
          dispatch({ type: "UPDATE_AGENT", agent: updatedFrom });
          updateAgent(updatedFrom).catch(() => {});
          const updatedTo = {
            ...agTo,
            connections: agTo.connections.filter((c) => c !== agFrom.id),
          };
          dispatch({ type: "UPDATE_AGENT", agent: updatedTo });
          updateAgent(updatedTo).catch(() => {});
        }

        // agent↔file (either direction): detach and revoke the matching
        // capability only if no other source of that same type remains
        // attached to this agent.
        const agent = agFrom ?? agTo;
        const src = srcTo ?? srcFrom;
        if (agent && src) {
          detachFile(agent.id, src.id).catch(() => {});
          const remainingSameTypeEdges = edges.filter(
            (edge) =>
              edge.id !== id &&
              (edge.from === agent.id || edge.to === agent.id) &&
              sources.some(
                (s) =>
                  (s.id === edge.from || s.id === edge.to) &&
                  s.type === src.type,
              ),
          );
          if (remainingSameTypeEdges.length === 0) {
            const revoked = capabilityToolsFor(src.type);
            const updatedTools = agent.tools.filter(
              (t) => !revoked.includes(t),
            );
            if (updatedTools.length !== agent.tools.length) {
              dispatch({
                type: "UPDATE_AGENT",
                agent: { ...agent, tools: updatedTools },
              });
              patchAgentTools(agent.id, updatedTools).catch(() => {});
            }
          }
        }
      }
      dispatch({ type: "DELETE_EDGE", id });
    },
    [edges, agents, sources],
  );

  const saveSource = useCallback(
    async (data: Source) => {
      const previous = sources.find((s) => s.id === data.id);
      if (previous) {
        dispatch({ type: "UPDATE_SOURCE", source: data });
        updateFileContent(data.id, data.name, data.content).catch(() => {});
      } else {
        dispatch({ type: "ADD_SOURCE", source: data });
        createFile(data.name, data.content, data.id).catch(() => {});
      }

      const previousAgentIds = previous?.agentIds ?? [];
      const newAgentIds = data.agentIds ?? [];
      // A type change (text ↔ dataset) on a source that stays attached to
      // the same agent must still re-derive that agent's capability — so it
      // is treated as a full detach-then-reattach for every agent in either
      // list, not just the ones whose membership actually changed.
      const typeChanged = previous !== undefined && previous.type !== data.type;

      const toDetach = typeChanged
        ? previousAgentIds
        : previousAgentIds.filter((id) => !newAgentIds.includes(id));
      const toAttach = typeChanged
        ? newAgentIds
        : newAgentIds.filter((id) => !previousAgentIds.includes(id));

      // Tracks each touched agent's tools as this function's own detach/attach
      // passes apply, so an agent present in both lists sees the detach's
      // revocation before the attach's grant is computed — dispatch() does
      // not apply synchronously, so re-reading `agents` between the two
      // passes would still see the pre-call snapshot.
      const toolsOverride = new Map<string, string[]>();
      const toolsFor = (agentId: string): string[] =>
        toolsOverride.get(agentId) ??
        agents.find((a) => a.id === agentId)?.tools ??
        [];

      for (const agentId of toDetach) {
        const edge = edges.find(
          (e) =>
            (e.from === agentId && e.to === data.id) ||
            (e.to === agentId && e.from === data.id),
        );
        if (!edge) continue;
        dispatch({ type: "DELETE_EDGE", id: edge.id });
        detachFile(agentId, data.id).catch(() => {});

        const remainingSameTypeEdges = edges.filter(
          (e) =>
            e.id !== edge.id &&
            (e.from === agentId || e.to === agentId) &&
            sources.some(
              (s) =>
                (s.id === e.from || s.id === e.to) &&
                s.type === (previous as Source).type,
            ),
        );
        if (remainingSameTypeEdges.length === 0) {
          const revoked = capabilityToolsFor((previous as Source).type);
          toolsOverride.set(
            agentId,
            toolsFor(agentId).filter((t) => !revoked.includes(t)),
          );
        }
      }

      for (const agentId of toAttach) {
        if (!agents.some((a) => a.id === agentId)) continue;
        dispatch({
          type: "ADD_EDGE",
          edge: { id: uuid(), from: agentId, to: data.id },
        });
        attachFile(agentId, data.id).catch(() => {});

        const current = toolsFor(agentId);
        const needed = capabilityToolsFor(data.type);
        const missing = needed.filter((t) => !current.includes(t));
        if (missing.length > 0) {
          toolsOverride.set(agentId, [...current, ...missing]);
        }
      }

      for (const [agentId, tools] of toolsOverride) {
        const agent = agents.find((a) => a.id === agentId);
        if (!agent) continue;
        dispatch({ type: "UPDATE_AGENT", agent: { ...agent, tools } });
        patchAgentTools(agentId, tools).catch(() => {});
      }
    },
    [sources, edges, agents],
  );

  const deleteSource = useCallback(
    (id: string) => {
      edges
        .filter((e) => e.from === id || e.to === id)
        .forEach((e) => deleteEdge(e.id));
      dispatch({ type: "DELETE_SOURCE", id });
      deleteFileApi(id).catch(() => {});
    },
    [edges, deleteEdge],
  );

  const connectNodes = useCallback(
    (from: string, to: string) => {
      dispatch({ type: "ADD_EDGE", edge: { id: uuid(), from, to } });

      // Resolve both directions — user may drag file→agent or agent→file
      const agFrom = agents.find((a) => a.id === from);
      const agTo = agents.find((a) => a.id === to);
      const srcFrom = sources.find((s) => s.id === from);
      const srcTo = sources.find((s) => s.id === to);

      // The "owning" agent and the file (whichever side they're on)
      const agent = agFrom ?? agTo;
      const src = srcTo ?? srcFrom;

      // agent→agent: persist the new connection to both agents
      if (agFrom && agTo) {
        if (!agFrom.connections.includes(agTo.id)) {
          const updated = {
            ...agFrom,
            connections: [...agFrom.connections, agTo.id],
          };
          dispatch({ type: "UPDATE_AGENT", agent: updated });
          updateAgent(updated).catch(() => {});
        }
        if (!agTo.connections.includes(agFrom.id)) {
          const updated = {
            ...agTo,
            connections: [...agTo.connections, agFrom.id],
          };
          dispatch({ type: "UPDATE_AGENT", agent: updated });
          updateAgent(updated).catch(() => {});
        }
      }

      // agent↔file (either direction): attach in DB and grant the matching capability
      if (agent && src) {
        attachFile(agent.id, src.id).catch(() => {});
        const needed = capabilityToolsFor(src.type);
        const missing = needed.filter((t) => !agent.tools.includes(t));
        if (missing.length > 0) {
          const updatedTools = [...agent.tools, ...missing];
          dispatch({
            type: "UPDATE_AGENT",
            agent: { ...agent, tools: updatedTools },
          });
          patchAgentTools(agent.id, updatedTools).catch(() => {});
        }
      }
    },
    [agents, sources],
  );

  return {
    agents,
    sources,
    edges,
    dispatch,
    saveAgent,
    deleteAgent,
    saveSource,
    deleteSource,
    connectNodes,
    deleteEdge,
  };
}
