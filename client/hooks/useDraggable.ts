import { useRef, useCallback } from "react";
import { Position } from "@/lib/types";

export function useDraggable(
  id: string,
  position: Position,
  onSelect: (id: string, e: React.MouseEvent) => void,
  onDragEnd: (id: string, pos: Position) => void,
  simMode: boolean,
  zoom: number = 1,
) {
  const dragging = useRef(false);
  // store start screen position and start world position separately
  const startClient = useRef({ x: 0, y: 0 });
  const startWorld = useRef({ x: 0, y: 0 });

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest(".connect-handle")) return;
      e.stopPropagation();
      onSelect(id, e);
      if (simMode) return;
      dragging.current = true;
      startClient.current = { x: e.clientX, y: e.clientY };
      startWorld.current = { x: position.x, y: position.y };
      const onMove = (me: MouseEvent) => {
        if (!dragging.current) return;
        onDragEnd(id, {
          x: startWorld.current.x + (me.clientX - startClient.current.x) / zoom,
          y: startWorld.current.y + (me.clientY - startClient.current.y) / zoom,
        });
      };
      const onUp = () => {
        dragging.current = false;
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [id, position, onSelect, onDragEnd, simMode, zoom],
  );

  return { onMouseDown };
}
