// Upload: analysis starts the moment the file lands.
import { useRef, useState } from "react";
import { api, errorText, uploadMedia, type Config } from "../api";
import { FileCard } from "../components/bits";

interface Props {
  config: Config | undefined;
  packId: string | undefined;
  upload: { name: string; fraction: number } | null;
  onProgress: (u: { name: string; fraction: number } | null) => void;
  onUploaded: (caseId: string) => void;
}

export function UploadStep({ config, packId, upload, onProgress, onUploaded }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const take = async (file: File | undefined) => {
    if (!file || upload) return;
    setError(null);
    if (config && file.size > config.max_upload_mb * 1024 * 1024) { setError(`That file is over the ${config.max_upload_mb} MB limit.`); return; }
    onProgress({ name: file.name, fraction: 0 });
    try {
      const { id } = await api.createCase(packId);
      await uploadMedia(id, file, (fraction) => onProgress({ name: file.name, fraction }));
      onUploaded(id);
    } catch (e) {
      onProgress(null);
      setError(errorText(e));
    }
  };

  return (
    <div className="panel-body">
      <div className="stack gap12">
        <span className="badge mono11">New report</span>
        <h1>Upload a recording</h1>
        <p className="muted">Video or audio. Analysis starts the moment the file lands, while you fill in the rest.</p>
      </div>
      {upload ? (
        <FileCard name={upload.name} durationS={null} triage={{ phase: "uploading", fraction: upload.fraction, doneS: 0, totalS: 0, proposed: 0 }} />
      ) : (
        <div className={`dropzone${over ? " over" : ""}${error ? " bad" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files[0]); }}>
          <span aria-hidden="true" className="up">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="#F4F1E8" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M9 13V3" /><path d="M5 7l4-4 4 4" /><path d="M3 15h12" /></svg>
          </span>
          <div style={{ fontWeight: 500, fontSize: 17 }}>Drop files here</div>
          <div className="mono11">MP4 · MOV · MKV · WAV · MP3</div>
          <button type="button" className="pill" onClick={() => input.current?.click()}>Browse files</button>
          <input ref={input} type="file" accept="video/*,audio/*,.mkv,.mov,.mp4,.wav,.mp3,.m4a" className="sr-only" tabIndex={-1} aria-label="Choose a recording"
                 onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }} />
          {error && <div className="error-line" role="alert">{error}</div>}
        </div>
      )}
      <section aria-label="What makes a clip easier to locate" className="stack gap12">
        <h2 className="mono11" style={{ margin: 0 }}>Easier to locate when it is</h2>
        <ul className="bullets">
          <li><span aria-hidden="true" className="sq" /><span>Recorded outdoors or by an open window</span></li>
          <li><span aria-hidden="true" className="sq" /><span>Uncut, and several minutes or longer</span></li>
          <li><span aria-hidden="true" className="sq" /><span>From a known date</span></li>
        </ul>
      </section>
      <p className="mono11 dim" style={{ marginTop: "auto" }}>Every report is logged to your account</p>
    </div>
  );
}
