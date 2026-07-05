"use client";
import { useEffect, useRef } from "react";
import "@xterm/xterm/css/xterm.css";
import { wsUrl } from "@/lib/api";

// xterm accesses `self` at module scope, so it must be imported in the
// browser only — never during SSR.
export default function Terminal({ sessionId, kind = "sessions" }: {
  sessionId: string;
  kind?: "sessions" | "auth";
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    let ws: WebSocket | undefined;
    let term: import("@xterm/xterm").Terminal | undefined;
    let disposed = false;
    let onResize: (() => void) | undefined;

    (async () => {
      const [{ Terminal: XTerm }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (disposed || !ref.current) return;

      term = new XTerm({ fontSize: 13, convertEol: true, cursorBlink: true });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(ref.current);
      fit.fit();

      const url =
        kind === "auth"
          ? wsUrl(`/ws/auth/${sessionId}`)
          : wsUrl(`/ws/sessions/${sessionId}/terminal`);
      ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";

      ws.onopen = () =>
        ws!.send(JSON.stringify({ type: "resize", rows: term!.rows, cols: term!.cols }));
      ws.onmessage = (ev) => {
        if (typeof ev.data === "string") {
          const msg = JSON.parse(ev.data);
          if (msg.type === "closed") term!.write(`\r\n[session ${msg.status}]\r\n`);
        } else {
          term!.write(new Uint8Array(ev.data));
        }
      };
      term.onData((d) => ws?.readyState === 1 && ws.send(JSON.stringify({ type: "input", data: d })));

      onResize = () => {
        fit.fit();
        if (ws?.readyState === 1)
          ws.send(JSON.stringify({ type: "resize", rows: term!.rows, cols: term!.cols }));
      };
      window.addEventListener("resize", onResize);
    })();

    return () => {
      disposed = true;
      if (onResize) window.removeEventListener("resize", onResize);
      ws?.close();
      term?.dispose();
    };
  }, [sessionId, kind]);

  return <div ref={ref} className="h-[480px] w-full rounded bg-black p-2" />;
}
