"use client";

import { useReducer, useEffect, useCallback } from "react";
import { CanvasState, CanvasAction, Agent, Edge, Source } from "@/lib/types";
import { uuid, autoLayout } from "@/lib/utils";
import {
  fetchAgents,
  fetchFiles,
  fetchAgentFiles,
  createAgent,
  updateAgent,
  deleteAgentApi,
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
        type: "text" as const,
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

  const saveSource = useCallback(
    (data: Source) => {
      if (sources.find((s) => s.id === data.id))
        dispatch({ type: "UPDATE_SOURCE", source: data });
      else dispatch({ type: "ADD_SOURCE", source: data });
    },
    [sources],
  );

  const deleteSource = useCallback((id: string) => {
    dispatch({ type: "DELETE_SOURCE", id });
  }, []);

  const connectNodes = useCallback(
    (from: string, to: string) => {
      dispatch({ type: "ADD_EDGE", edge: { id: uuid(), from, to } });
      const ag = agents.find((a) => a.id === from);
      if (ag && !ag.connections.includes(to))
        dispatch({
          type: "UPDATE_AGENT",
          agent: { ...ag, connections: [...ag.connections, to] },
        });
    },
    [agents],
  );

  const deleteEdge = useCallback(
    (id: string) => {
      const e = edges.find((e) => e.id === id);
      if (e) {
        const ag = agents.find((a) => a.id === e.from);
        if (ag)
          dispatch({
            type: "UPDATE_AGENT",
            agent: {
              ...ag,
              connections: ag.connections.filter((c) => c !== e.to),
            },
          });
      }
      dispatch({ type: "DELETE_EDGE", id });
    },
    [edges, agents],
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
