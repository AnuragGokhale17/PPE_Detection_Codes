"use client";

import { Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";

/** Grabs one frame through the API so the person configuring a camera sees it works before saving. */
export function StreamTest({ streamUrl, cameraId }: { streamUrl: string; cameraId?: number }) {
  const [state, setState] = useState<{ busy: boolean; image: string | null; error: string | null }>({
    busy: false,
    image: null,
    error: null,
  });
  const imageRef = useRef<string | null>(null);

  useEffect(
    () => () => {
      if (imageRef.current) URL.revokeObjectURL(imageRef.current);
    },
    [],
  );

  async function run() {
    setState((s) => ({ ...s, busy: true, error: null }));
    try {
      const res = await fetch("/api/config/stream-test", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "image/jpeg, application/json" },
        body: JSON.stringify({ stream_url: streamUrl.trim(), camera_id: cameraId ?? null }),
      });
      if (!res.ok) {
        if (res.status === 401) window.dispatchEvent(new CustomEvent("ppe:unauthorized"));
        let message = `The test failed (${res.status}).`;
        try {
          const body = await res.json();
          const detail = body?.detail;
          if (typeof detail === "string") message = detail;
          else if (Array.isArray(detail)) message = detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, "")).join(". ");
        } catch {
          /* non-JSON error body */
        }
        setState({ busy: false, image: imageRef.current, error: message });
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      if (imageRef.current) URL.revokeObjectURL(imageRef.current);
      imageRef.current = url;
      setState({ busy: false, image: url, error: null });
    } catch {
      setState({ busy: false, image: imageRef.current, error: "Could not reach the server." });
    }
  }

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-outline btn-sm" onClick={run} disabled={state.busy || streamUrl.trim().length < 8}>
          {state.busy ? <Spinner /> : <Video className="size-3.5" aria-hidden />} Test stream
        </button>
        <span className="text-xs text-ink-3" aria-live="polite">
          {state.busy ? "Connecting to the camera. This can take up to 15 seconds…" : "Grabs one frame from the camera."}
        </span>
      </div>
      {state.error && <Alert tone="critical">{state.error}</Alert>}
      {state.image && !state.error && (
        // eslint-disable-next-line @next/next/no-img-element -- blob URL from the API, not an optimisable asset
        <img
          src={state.image}
          alt="Current frame from this camera"
          className="w-full rounded-md border border-line bg-surface-sunken object-contain"
          style={{ aspectRatio: "16 / 9" }}
        />
      )}
    </div>
  );
}
