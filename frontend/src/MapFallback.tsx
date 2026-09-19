import { ReactFlow, Background, Controls } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Network, Route } from "./api";
export default function MapFallback({
  network,
  selected,
}: {
  network: Network;
  selected?: Route;
}) {
  return (
    <div style={{ height: "100%", width: "100%" }}>
      <ReactFlow
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        nodes={network.nodes.map((n) => ({
          id: n.id,
          position: { x: (n.longitude - 2) * 60, y: (54 - n.latitude) * 110 },
          data: { label: n.name },
        }))}
        edges={network.lanes.map((l) => ({
          id: l.id,
          source: l.from_node_id,
          target: l.to_node_id,
          style: {
            stroke: selected?.lane_ids.includes(l.id) ? "#386be8" : "#9babb7",
            strokeWidth: 3,
          },
          label: l.mode,
        }))}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
