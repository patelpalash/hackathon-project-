import { useState } from "react";
import { ReactFlow, Background, Controls, MarkerType } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Save, GitBranch } from "lucide-react";
import type { Bundle } from "./App";
import { intent, type Model } from "./api";
export default function Schedules({
  bundle,
  busy,
  mutate,
}: {
  bundle: Bundle;
  busy: boolean;
  mutate: (path: string, body: unknown, method?: string) => Promise<any>;
}) {
  const [target, setTarget] = useState<{
    kind: "node" | "lane";
    id: string;
    snapshot: Bundle["state"]["snapshot"];
    active: boolean;
    minutes: number;
    departures: Model<"DepartureRule">[];
  }>();
  const open = (kind: "node" | "lane", id: string) => {
    const item =
      kind === "node"
        ? bundle.network.nodes.find((n) => n.id === id)!
        : bundle.network.lanes.find((l) => l.id === id)!;
    setTarget({
      kind,
      id,
      snapshot: bundle.state.snapshot,
      active: item.active,
      minutes:
        "processing_minutes" in item
          ? item.processing_minutes
          : item.duration_minutes,
      departures: "departures" in item ? item.departures : [],
    });
  };
  const stale =
    !!target &&
    JSON.stringify(target.snapshot) !== JSON.stringify(bundle.state.snapshot);
  const nodes = bundle.network.nodes.map((n) => ({
    id: n.id,
    position: { x: (n.longitude - 2) * 75, y: (54 - n.latitude) * 120 },
    data: { label: n.name },
    style: {
      borderRadius: 12,
      border: `1px solid ${n.active ? "#b8cbc9" : "#e0a3a3"}`,
      background: n.active ? "#fff" : "#fff0ee",
      fontSize: 12,
      width: 155,
      padding: 15,
    },
  }));
  const edges = bundle.network.lanes.map((l) => ({
    id: l.id,
    source: l.from_node_id,
    target: l.to_node_id,
    label: `${l.mode} · ${l.duration_minutes}m`,
    animated: l.mode === "air",
    style: { stroke: l.active ? "#4b79ce" : "#c9c9c9", strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
  return (
    <div className="schedule-grid">
      <div className="card">
        <div className="section-title">
          <h2>Scheduled service network</h2>
          <span className="muted">Select a facility or connection</span>
        </div>
        <div style={{ height: 570 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            onNodeClick={(_, n) => open("node", n.id)}
            onEdgeClick={(_, e) => open("lane", e.id)}
          >
            <Background color="#d9e2e5" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </div>
      <section className="card padded">
        {!target ? (
          <div className="empty-state">
            <GitBranch size={32} />
            <h3>Inspect the network</h3>
            <p>
              Select a node or lane to review and edit its operational
              parameters.
            </p>
          </div>
        ) : (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await mutate(
                  `/${target.kind === "node" ? "nodes" : "lanes"}/${target.id}`,
                  {
                    mutation_id: intent(),
                    expected_snapshot: target.snapshot,
                    active: target.active,
                    ...(target.kind === "node"
                      ? { processing_minutes: target.minutes }
                      : {
                          duration_minutes: target.minutes,
                          departures: target.departures,
                        }),
                  },
                  "PATCH",
                );
                setTarget(undefined);
              } catch {}
            }}
          >
            <span className="eyebrow">
              {target.kind.toUpperCase()} SETTINGS
            </span>
            <h2>{target.id}</h2>
            <p className="muted">
              Edits recalculate affected searches and saved plans.
            </p>
            {stale && (
              <div className="alert error">
                Conditions changed. Draft preserved.
                <button
                  type="button"
                  onClick={() => open(target.kind, target.id)}
                >
                  Reload
                </button>
              </div>
            )}
            <label className="checkbox">
              <input
                type="checkbox"
                checked={target.active}
                onChange={(e) =>
                  setTarget({ ...target, active: e.target.checked })
                }
              />
              Service active
            </label>
            <label>
              {target.kind === "node" ? "Handling" : "Movement"} duration
              (minutes)
              <input
                type="number"
                min={target.kind === "node" ? 0 : 1}
                required
                value={target.minutes}
                onChange={(e) =>
                  setTarget({ ...target, minutes: Number(e.target.value) })
                }
              />
            </label>
            {target.kind === "lane" && (
              <>
                <p className="muted">
                  Validity:{" "}
                  {
                    bundle.network.lanes.find((l) => l.id === target.id)
                      ?.valid_from
                  }{" "}
                  →{" "}
                  {
                    bundle.network.lanes.find((l) => l.id === target.id)
                      ?.valid_to
                  }{" "}
                  (read-only)
                </p>
                <h3>Departure rules</h3>
                {target.departures.map((d, i) => (
                  <fieldset key={d.id}>
                    <legend>{d.id}</legend>
                    <div className="two-cols">
                      <label>
                        Local departure
                        <input
                          type="time"
                          required
                          value={d.local_time}
                          onChange={(e) =>
                            setTarget({
                              ...target,
                              departures: target.departures.map((r, j) =>
                                j === i
                                  ? { ...r, local_time: e.target.value }
                                  : r,
                              ),
                            })
                          }
                        />
                      </label>
                      <label>
                        Cutoff (minutes)
                        <input
                          type="number"
                          min={0}
                          required
                          value={d.cutoff_minutes}
                          onChange={(e) =>
                            setTarget({
                              ...target,
                              departures: target.departures.map((r, j) =>
                                j === i
                                  ? {
                                      ...r,
                                      cutoff_minutes: Number(e.target.value),
                                    }
                                  : r,
                              ),
                            })
                          }
                        />
                      </label>
                    </div>
                    <div className="weekdays">
                      {["M", "T", "W", "T", "F", "S", "S"].map((name, day) => (
                        <button
                          type="button"
                          key={day}
                          className={
                            d.weekdays.includes(day + 1) ? "selected" : ""
                          }
                          aria-label={`ISO weekday ${day + 1}`}
                          aria-pressed={d.weekdays.includes(day + 1)}
                          onClick={() =>
                            setTarget({
                              ...target,
                              departures: target.departures.map((r, j) =>
                                j === i
                                  ? {
                                      ...r,
                                      weekdays: r.weekdays.includes(day + 1)
                                        ? r.weekdays.filter(
                                            (v) => v !== day + 1,
                                          )
                                        : [...r.weekdays, day + 1].sort(),
                                    }
                                  : r,
                              ),
                            })
                          }
                        >
                          {name}
                        </button>
                      ))}
                    </div>
                  </fieldset>
                ))}
              </>
            )}
            <button
              className="button primary wide"
              disabled={
                busy ||
                stale ||
                target.departures.some((d) => !d.weekdays.length)
              }
            >
              <Save size={16} />
              Save changes
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
