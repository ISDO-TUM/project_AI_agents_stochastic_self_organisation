import { useRef, useCallback } from "react";
import { Position } from "@/lib/types";

export function useDraggable(
  id: string,
  position: Position,
  onSelect: (id: string, e: React.MouseEvent) => void,
  onDragEnd: (id: string, pos: Position) => void,
  simMode: boolean,
) {
  const dragging = useRef(false);
  const dragOffset = useRef({ x: 0, y: 0 });

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest(".connect-handle")) return;
      e.stopPropagation();
      onSelect(id, e);
      if (simMode) return;
      dragging.current = true;
      dragOffset.current = {
        x: e.clientX - position.x,
        y: e.clientY - position.y,
      };
      const onMove = (me: MouseEvent) => {
        if (!dragging.current) return;
        onDragEnd(id, {
          x: me.clientX - dragOffset.current.x,
          y: me.clientY - dragOffset.current.y,
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
    [id, position, onSelect, onDragEnd, simMode],
  );

  return { onMouseDown };
}
