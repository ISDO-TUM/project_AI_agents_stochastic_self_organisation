"use client";

import { useReducer, useEffect, useCallback } from "react";
import { CanvasState, CanvasAction, Agent, Source } from "@/lib/types";
import { uuid, autoLayout } from "@/lib/utils";
import {
  fetchAgents,
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
    fetchAgents()
      .then((list) => {
        dispatch({
          type: "LOAD",
          state: { agents: list, sources: [], edges: [] },
        });
      })
      .catch(() => {});
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

  const saveSource = useCallback(
    async (data: Source) => {
      const exists = sources.find((s) => s.id === data.id);
      if (exists) {
        dispatch({ type: "UPDATE_SOURCE", source: data });
        updateFileContent(data.id, data.name, data.content).catch(() => {});
      } else {
        dispatch({ type: "ADD_SOURCE", source: data });
        createFile(data.name, data.content, data.id).catch(() => {});
      }
    },
    [sources],
  );

  const deleteSource = useCallback(
    (id: string) => {
      dispatch({ type: "DELETE_SOURCE", id });
      deleteFileApi(id).catch(() => {});
    },
    [],
  );

  const connectNodes = useCallback(
    (from: string, to: string) => {
      dispatch({ type: "ADD_EDGE", edge: { id: uuid(), from, to } });

      // agent→agent: update connections list
      const agFrom = agents.find((a) => a.id === from);
      if (agFrom && !agFrom.connections.includes(to)) {
        dispatch({
          type: "UPDATE_AGENT",
          agent: { ...agFrom, connections: [...agFrom.connections, to] },
        });
      }

      // source→agent: attach file + auto-check "files" tool
      const srcFrom = sources.find((s) => s.id === from);
      const agTo = agents.find((a) => a.id === to);
      if (srcFrom && agTo) {
        attachFile(agTo.id, srcFrom.id).catch(() => {});
        if (!agTo.tools.includes("files")) {
          const updatedTools = [...agTo.tools, "files"];
          dispatch({
            type: "UPDATE_AGENT",
            agent: { ...agTo, tools: updatedTools },
          });
          patchAgentTools(agTo.id, updatedTools).catch(() => {});
        }
      }
    },
    [agents, sources],
  );

  const deleteEdge = useCallback(
    (id: string) => {
      const e = edges.find((edge) => edge.id === id);
      if (e) {
        // agent→agent: remove from connections list
        const agFrom = agents.find((a) => a.id === e.from);
        if (agFrom) {
          dispatch({
            type: "UPDATE_AGENT",
            agent: {
              ...agFrom,
              connections: agFrom.connections.filter((c) => c !== e.to),
            },
          });
        }

        // source→agent: detach file + maybe uncheck "files" tool
        const srcFrom = sources.find((s) => s.id === e.from);
        const agTo = agents.find((a) => a.id === e.to);
        if (srcFrom && agTo) {
          detachFile(agTo.id, srcFrom.id).catch(() => {});
          const remainingSources = edges.filter(
            (edge) =>
              edge.id !== id &&
              edge.to === agTo.id &&
              sources.some((s) => s.id === edge.from),
          );
          if (remainingSources.length === 0) {
            const updatedTools = agTo.tools.filter((t) => t !== "files");
            dispatch({
              type: "UPDATE_AGENT",
              agent: { ...agTo, tools: updatedTools },
            });
            patchAgentTools(agTo.id, updatedTools).catch(() => {});
          }
        }
      }
      dispatch({ type: "DELETE_EDGE", id });
    },
    [edges, agents, sources],
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
