"use client";

import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Card } from "@/components/ui";

export function LiveBrowser({ url, label, snapshot }: { url: string; label: string; snapshot?: string | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const socket = new WebSocket(url);
    socketRef.current = socket;
    socket.onopen = () => {
      if (!active) return;
      setConnected(true);
      setError(null);
    };
    socket.onclose = (event) => {
      if (!active) return;
      setConnected(false);
      setError(event.reason || `Connection closed (${event.code})`);
    };
    socket.onerror = () => {
      if (!active) return;
      setConnected(false);
      setError("Could not connect to this browser session.");
    };
    socket.onmessage = (message) => {
      if (!active || typeof message.data !== "string") return;
      try {
        const frame = JSON.parse(message.data);
        const canvas = canvasRef.current;
        const context = canvas?.getContext("2d");
        if (frame.type !== "frame" || !canvas || !context || typeof frame.data !== "string") return;
        const image = new Image();
        image.onload = () => {
          if (!active) return;
          canvas.width = frame.metadata?.deviceWidth || image.naturalWidth;
          canvas.height = frame.metadata?.deviceHeight || image.naturalHeight;
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ack", seq: frame.seq }));
        };
        image.src = `data:image/jpeg;base64,${frame.data}`;
      } catch {
        // Ignore malformed stream messages while preserving the session.
      }
    };
    return () => {
      active = false;
      socket.close();
      if (socketRef.current === socket) socketRef.current = null;
    };
  }, [url]);

  useEffect(() => {
    if (!snapshot) return;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const image = new Image();
    image.onload = () => {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
    };
    image.src = snapshot;
  }, [snapshot]);

  function send(event: Record<string, unknown>) {
    if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify(event));
  }

  function coordinates(event: Pick<ReactPointerEvent<HTMLCanvasElement>, "currentTarget" | "clientX" | "clientY">) {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.round((event.clientX - rect.left) * event.currentTarget.width / rect.width),
      y: Math.round((event.clientY - rect.top) * event.currentTarget.height / rect.height),
    };
  }

  return (
    <Card title={connected ? `Live browser · ${label}` : error ? "Browser disconnected" : "Connecting to browser…"}>
      <canvas
        ref={canvasRef}
        aria-label="Live remote browser. Click here, then use your mouse and keyboard to control it."
        tabIndex={0}
        className="block w-full rounded border border-line bg-black outline-none focus:ring-2 focus:ring-accent"
        style={{ aspectRatio: "16 / 9", objectFit: "contain" }}
        onPointerDown={(event) => {
          event.currentTarget.focus();
          event.currentTarget.setPointerCapture(event.pointerId);
          send({ type: "input_mouse", eventType: "mousePressed", ...coordinates(event), button: event.button === 2 ? "right" : event.button === 1 ? "middle" : "left", clickCount: 1 });
        }}
        onPointerUp={(event) => send({ type: "input_mouse", eventType: "mouseReleased", ...coordinates(event), button: event.button === 2 ? "right" : event.button === 1 ? "middle" : "left" })}
        onPointerMove={(event) => { if (event.buttons) send({ type: "input_mouse", eventType: "mouseMoved", ...coordinates(event) }); }}
        onContextMenu={(event) => event.preventDefault()}
        onWheel={(event) => send({ type: "input_mouse", eventType: "mouseWheel", ...coordinates(event), deltaX: event.deltaX, deltaY: event.deltaY })}
        onKeyDown={(event) => {
          event.preventDefault();
          if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) send({ type: "input_keyboard", eventType: "char", text: event.key });
          else send({ type: "input_keyboard", eventType: "keyDown", key: event.key, code: event.code });
        }}
        onKeyUp={(event) => {
          if (event.key.length !== 1 || event.ctrlKey || event.altKey || event.metaKey) send({ type: "input_keyboard", eventType: "keyUp", key: event.key, code: event.code });
        }}
      />
      <p className="mt-2 text-xs text-muted">
        Sign in directly in this browser if the site asks. JobPilot does not read or store your password. Use the browser to inspect results and open a job; application form filling and submission remain separate steps.
      </p>
      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
    </Card>
  );
}
