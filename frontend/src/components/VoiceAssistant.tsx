import { useState, useEffect, useRef, useCallback } from "react";
import { getAuthHeaders } from "../auth";

export type VoiceState =
  | "IDLE"
  | "LISTENING"
  | "SPEECH_DETECTED"
  | "TRANSCRIBING"
  | "PROCESSING"
  | "EXECUTING"
  | "SPEAKING"
  | "INTERRUPTED"
  | "STOPPED";

interface VoiceAssistantProps {
  apiUrl: string;
  onSwitchToTextChat?: () => void;
}

interface SpeechRecognitionResultItem {
  transcript: string;
}

interface SpeechRecognitionResult {
  isFinal: boolean;
  [index: number]: SpeechRecognitionResultItem;
}

interface SpeechRecognitionResultList {
  length: number;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionEvent {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

interface ISpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onspeechstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

interface ExtendedWindow extends Window {
  SpeechRecognition?: new () => ISpeechRecognition;
  webkitSpeechRecognition?: new () => ISpeechRecognition;
  AudioContext?: typeof AudioContext;
  webkitAudioContext?: typeof AudioContext;
}

export default function VoiceAssistant({ apiUrl, onSwitchToTextChat }: VoiceAssistantProps) {
  // Conversational State Machine
  const [state, setState] = useState<VoiceState>("IDLE");
  const [isSessionActive, setIsSessionActive] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [spokenStatusText, setSpokenStatusText] = useState("Click 'Start Voice Conversation' to begin.");
  const [systemMetrics, setSystemMetrics] = useState<{
    cpu?: number;
    ram_used?: number;
    ram_free?: number;
    battery?: number;
  }>({});
  const [showLog, setShowLog] = useState(false);
  const [sessionLogs, setSessionLogs] = useState<Array<{ id: string; sender: "user" | "kela"; text: string; time: string }>>([]);

  // Audio & Speech References
  const recognitionRef = useRef<ISpeechRecognition | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ttsSafetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const transcriptBufferRef = useRef<string>("");
  const stateRef = useRef<VoiceState>("IDLE");
  const isSpeakingRef = useRef<boolean>(false);
  const isProcessingRef = useRef<boolean>(false);
  const isSessionActiveRef = useRef<boolean>(false);

  // Ref bridges to break circular callback dependencies
  const triggerBargeInRef = useRef<() => void>(() => { /* bridge */ });
  const resumeListeningRef = useRef<() => void>(() => { /* bridge */ });
  const stopVoiceSessionRef = useRef<() => void>(() => { /* bridge */ });
  const processVoiceUtteranceRef = useRef<(text: string) => Promise<void>>(async () => { /* bridge */ });
  const speakVoiceResponseRef = useRef<(text: string, lang?: string, shouldStopSession?: boolean) => void>(() => { /* bridge */ });

  // Sync refs with state
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    isSessionActiveRef.current = isSessionActive;
  }, [isSessionActive]);

  // Fetch initial system telemetry
  useEffect(() => {
    void (async () => {
      try {
        const authHeaders = await getAuthHeaders(apiUrl);
        const r = await fetch(`${apiUrl}/api/pc/system`, { headers: authHeaders });
        if (r.ok) {
          const data = (await r.json()) as { metrics?: { cpu_load_percent?: number; used_ram_mb?: number; free_ram_mb?: number; battery_percent?: number } };
          if (data?.metrics) {
            setSystemMetrics({
              cpu: data.metrics.cpu_load_percent,
              ram_used: data.metrics.used_ram_mb,
              ram_free: data.metrics.free_ram_mb,
              battery: data.metrics.battery_percent,
            });
          }
        }
      } catch (err: unknown) {
        console.debug("System metrics unavailable:", err);
      }
    })();
  }, [apiUrl]);

  // Release Audio Analyser resources safely
  const releaseAudioAnalyser = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      try {
        void audioContextRef.current.close();
      } catch (err: unknown) {
        console.debug("AudioContext close error:", err);
      }
      audioContextRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
  }, []);

  // Stop Voice Session
  const stopVoiceSession = useCallback(() => {
    setIsSessionActive(false);
    isSessionActiveRef.current = false;
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (ttsSafetyTimerRef.current) {
      clearTimeout(ttsSafetyTimerRef.current);
      ttsSafetyTimerRef.current = null;
    }
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort();
      } catch {
        // intentional no-op on abort
      }
      recognitionRef.current = null;
    }
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    releaseAudioAnalyser();
    setState("STOPPED");
    setSpokenStatusText("Voice session ended. Click Start to resume.");
    setLiveTranscript("");
  }, [releaseAudioAnalyser]);

  useEffect(() => {
    stopVoiceSessionRef.current = stopVoiceSession;
  }, [stopVoiceSession]);

  // Instant Barge-In / Interruption
  const triggerBargeIn = useCallback(() => {
    if (ttsSafetyTimerRef.current) {
      clearTimeout(ttsSafetyTimerRef.current);
      ttsSafetyTimerRef.current = null;
    }
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    isSpeakingRef.current = false;
    isProcessingRef.current = false;
    setState("INTERRUPTED");
    setSpokenStatusText("I'm listening...");

    setTimeout(() => {
      if (isSessionActiveRef.current) {
        resumeListeningRef.current();
      } else {
        setState("IDLE");
      }
    }, 150);
  }, []);

  useEffect(() => {
    triggerBargeInRef.current = triggerBargeIn;
  }, [triggerBargeIn]);

  // Setup Web Audio Analyser with Real-time Echo Cancellation
  const initAudioAnalyser = useCallback(async () => {
    try {
      const extWin = window as ExtendedWindow;
      if (!audioContextRef.current) {
        const AudioContextClass = extWin.AudioContext || extWin.webkitAudioContext || window.AudioContext;
        audioContextRef.current = new AudioContextClass();
      }
      const audioCtx = audioContextRef.current;
      if (!audioCtx) return;

      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      if (!mediaStreamRef.current) {
        mediaStreamRef.current = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
      }

      if (!mediaStreamRef.current) return;

      const source = audioCtx.createMediaStreamSource(mediaStreamRef.current);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const drawWave = () => {
        animationFrameRef.current = requestAnimationFrame(drawWave);
        analyser.getByteFrequencyData(dataArray);

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Active Barge-in check: If user speaks while KELA is talking, interrupt immediately
        if (isSpeakingRef.current) {
          let energySum = 0;
          for (let i = 0; i < bufferLength; i++) {
            energySum += dataArray[i];
          }
          const avgEnergy = energySum / bufferLength;
          if (avgEnergy > 60) {
            triggerBargeInRef.current();
            return;
          }
        }

        const barWidth = (canvas.width / bufferLength) * 2.5;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          const barHeight = (dataArray[i] / 255) * canvas.height * 0.85;

          const grad = ctx.createLinearGradient(0, canvas.height, 0, 0);
          if (stateRef.current === "LISTENING" || stateRef.current === "SPEECH_DETECTED") {
            grad.addColorStop(0, "#00ff88");
            grad.addColorStop(1, "#00b4d8");
          } else if (stateRef.current === "SPEAKING") {
            grad.addColorStop(0, "#8a2be2");
            grad.addColorStop(1, "#ff007f");
          } else {
            grad.addColorStop(0, "rgba(255,255,255,0.2)");
            grad.addColorStop(1, "rgba(255,255,255,0.05)");
          }

          ctx.fillStyle = grad;
          ctx.fillRect(x, canvas.height - barHeight, barWidth - 1, barHeight);
          x += barWidth + 1;
        }
      };

      drawWave();
    } catch (err: unknown) {
      console.warn("Audio analyser unavailable:", err);
    }
  }, []);

  // Natural Spoken Speech (Text-To-Speech) with Fast Recovery
  const speakVoiceResponse = useCallback((text: string, lang = "english", shouldStopSession = false) => {
    if (!("speechSynthesis" in window)) {
      if (shouldStopSession) stopVoiceSessionRef.current();
      else resumeListeningRef.current();
      return;
    }

    if (ttsSafetyTimerRef.current) {
      clearTimeout(ttsSafetyTimerRef.current);
      ttsSafetyTimerRef.current = null;
    }

    // Cancel pending speech and resume audio context if paused
    window.speechSynthesis.cancel();
    window.speechSynthesis.resume();

    // Clean text to ensure only natural speech is spoken
    const cleanSpeech = text
      .replace(/[*_#`[\]()]/g, "")
      .replace(/https?:\/\/\S+/g, "link")
      .trim();

    if (!cleanSpeech) {
      if (shouldStopSession) stopVoiceSessionRef.current();
      else resumeListeningRef.current();
      return;
    }

    setSpokenStatusText(cleanSpeech);

    const utterance = new SpeechSynthesisUtterance(cleanSpeech);
    utterance.rate = 1.15; // Snappy, natural pace
    utterance.pitch = 1.0;

    const voices = window.speechSynthesis.getVoices();
    if (lang === "hinglish") {
      const hindiVoice = voices.find(
        (v) => v.lang.includes("hi") || v.name.includes("India") || v.name.includes("Hindi")
      );
      if (hindiVoice) utterance.voice = hindiVoice;
    } else {
      const preferredEnglishVoice = voices.find(
        (v) =>
          (v.lang.includes("en-IN") || v.lang.includes("en-US") || v.lang.includes("en-GB")) &&
          (v.name.includes("Natural") ||
            v.name.includes("Google") ||
            v.name.includes("Microsoft") ||
            v.name.includes("David") ||
            v.name.includes("Samantha"))
      );
      if (preferredEnglishVoice) utterance.voice = preferredEnglishVoice;
    }

    const onSpeechFinished = () => {
      if (ttsSafetyTimerRef.current) {
        clearTimeout(ttsSafetyTimerRef.current);
        ttsSafetyTimerRef.current = null;
      }
      isSpeakingRef.current = false;
      const timeStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      setSessionLogs((prev) => [
        ...prev,
        { id: String(Date.now() + 1), sender: "kela", text: cleanSpeech, time: timeStr },
      ]);

      if (shouldStopSession) {
        stopVoiceSessionRef.current();
      } else if (isSessionActiveRef.current) {
        // AUTOMATICALLY RESUME LISTENING IMMEDIATELY!
        resumeListeningRef.current();
      } else {
        setState("IDLE");
      }
    };

    utterance.onstart = () => {
      isSpeakingRef.current = true;
      setState("SPEAKING");
    };

    utterance.onend = onSpeechFinished;
    utterance.onerror = onSpeechFinished;

    // Safety timeout: prevents Chrome's speech engine from locking up the assistant
    const estimatedDurationMs = Math.max(2500, cleanSpeech.length * 80);
    ttsSafetyTimerRef.current = setTimeout(() => {
      if (isSpeakingRef.current) {
        console.log("TTS safety timeout triggered; auto-resuming listening.");
        window.speechSynthesis.cancel();
        onSpeechFinished();
      }
    }, estimatedDurationMs);

    window.speechSynthesis.speak(utterance);
  }, []);

  useEffect(() => {
    speakVoiceResponseRef.current = speakVoiceResponse;
  }, [speakVoiceResponse]);

  // Process Completed Voice Utterance (Autonomous Backend Pipeline)
  const processVoiceUtterance = useCallback(
    async (utteranceText: string) => {
      if (!utteranceText.trim() || isProcessingRef.current) return;

      // Clear any pending timers
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }

      isProcessingRef.current = true;
      setState("PROCESSING");
      setLiveTranscript(utteranceText);

      const timeStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      setSessionLogs((prev) => [
        ...prev,
        { id: String(Date.now()), sender: "user", text: utteranceText, time: timeStr },
      ]);

      // Stop speech recognizer temporarily during processing & speaking
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {
          // intentional no-op
        }
      }

      abortControllerRef.current = new AbortController();

      try {
        const response = await fetch(`${apiUrl}/api/voice/conversation`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: utteranceText }),
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error(`Server returned HTTP ${response.status}`);
        }

        const data = (await response.json()) as {
          response_text?: string;
          action?: string;
          lang?: string;
          fast_path?: boolean;
        };

        const spokenAnswer = data.response_text || "I have completed the task.";
        const lang = data.lang || "english";
        const isStopAction = data.action === "stop_listening";

        setState("EXECUTING");
        setSpokenStatusText(spokenAnswer);

        // Speak response aloud through SpeechSynthesis
        speakVoiceResponseRef.current(spokenAnswer, lang, isStopAction);
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") {
          console.log("Voice request aborted by user.");
          return;
        }
        console.error("Voice process error:", err);
        const fallbackMsg = "Sorry, I had trouble reaching the server. Please try again.";
        setSpokenStatusText(fallbackMsg);
        speakVoiceResponseRef.current(fallbackMsg, "english", false);
      } finally {
        isProcessingRef.current = false;
        abortControllerRef.current = null;
      }
    },
    [apiUrl]
  );

  useEffect(() => {
    processVoiceUtteranceRef.current = processVoiceUtterance;
  }, [processVoiceUtterance]);

  // Resume continuous listening loop
  const resumeListening = useCallback(() => {
    if (!isSessionActiveRef.current) return;
    if (isSpeakingRef.current || isProcessingRef.current) return;

    setState("LISTENING");
    setLiveTranscript("");
    transcriptBufferRef.current = "";

    const extWin = window as ExtendedWindow;
    const SpeechRecClass = extWin.SpeechRecognition || extWin.webkitSpeechRecognition;
    if (!SpeechRecClass) {
      setSpokenStatusText("Speech recognition not supported in this browser. Please use Chrome or Edge.");
      return;
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort();
      } catch {
        // intentional no-op
      }
    }

    const recognition = new SpeechRecClass();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-IN";
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setState("LISTENING");
    };

    recognition.onspeechstart = () => {
      setState("SPEECH_DETECTED");
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      if (isSpeakingRef.current || isProcessingRef.current) return;

      let interim = "";
      let finalStr = "";

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const item = event.results[i];
        if (item.isFinal) {
          finalStr += item[0].transcript;
        } else {
          interim += item[0].transcript;
        }
      }

      // If browser detected final end of sentence: SUBMIT IMMEDIATELY! NO WAITING!
      if (finalStr.trim()) {
        if (silenceTimerRef.current) {
          clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = null;
        }
        transcriptBufferRef.current = "";
        void processVoiceUtteranceRef.current(finalStr.trim());
        return;
      }

      // If user is currently speaking: display live words and set quick 650ms silence fallback
      if (interim.trim()) {
        setState("TRANSCRIBING");
        setLiveTranscript(interim);
        transcriptBufferRef.current = interim.trim();

        if (silenceTimerRef.current) {
          clearTimeout(silenceTimerRef.current);
        }

        // Quick 650ms VAD silence timeout
        silenceTimerRef.current = setTimeout(() => {
          const textToSubmit = transcriptBufferRef.current;
          transcriptBufferRef.current = "";
          if (textToSubmit && !isProcessingRef.current && !isSpeakingRef.current) {
            void processVoiceUtteranceRef.current(textToSubmit);
          }
        }, 650);
      }
    };

    recognition.onerror = (event: { error: string }) => {
      if (event.error === "no-speech") return;
      console.warn("Speech recognition notice:", event.error);
    };

    recognition.onend = () => {
      if (isSessionActiveRef.current && !isSpeakingRef.current && !isProcessingRef.current) {
        try {
          recognition.start();
        } catch {
          // intentional no-op
        }
      }
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch (e: unknown) {
      console.warn("Recognition start issue:", e);
    }
  }, []);

  useEffect(() => {
    resumeListeningRef.current = resumeListening;
  }, [resumeListening]);

  // Start Voice Session
  const startVoiceSession = useCallback(async () => {
    setIsSessionActive(true);
    isSessionActiveRef.current = true;
    await initAudioAnalyser();
    resumeListeningRef.current();
    setSpokenStatusText("Listening to you...");
  }, [initAudioAnalyser]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      if (ttsSafetyTimerRef.current) clearTimeout(ttsSafetyTimerRef.current);
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {
          // intentional no-op
        }
      }
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
      releaseAudioAnalyser();
    };
  }, [releaseAudioAnalyser]);

  return (
    <div className="voice-assistant-container">
      {/* Top Telemetry Bar */}
      <div className="voice-metrics-bar">
        <div className="metric-pill">
          <span className="dot online"></span>
          <span>KELA FAST VOICE</span>
        </div>
        {systemMetrics.cpu !== undefined && (
          <div className="metric-pill">
            <span>CPU: <strong>{systemMetrics.cpu}%</strong></span>
          </div>
        )}
        {systemMetrics.ram_free !== undefined && (
          <div className="metric-pill">
            <span>Free RAM: <strong>{systemMetrics.ram_free} MB</strong></span>
          </div>
        )}
        {systemMetrics.battery !== undefined && (
          <div className="metric-pill">
            <span>Battery: <strong>{systemMetrics.battery}%</strong></span>
          </div>
        )}
        <div className="metric-pill right">
          <span>Continuous Loop: <strong>{isSessionActive ? "ACTIVE" : "PAUSED"}</strong></span>
        </div>
      </div>

      {/* Main Central Futuristic AI Orb */}
      <div className="orb-stage">
        <div
          className={`kela-orb ${state.toLowerCase()}`}
          onClick={state === "SPEAKING" ? triggerBargeIn : isSessionActive ? stopVoiceSession : () => { void startVoiceSession(); }}
          title={state === "SPEAKING" ? "Click to interrupt speech" : isSessionActive ? "Click to pause" : "Click to start voice"}
        >
          <div className="orb-core"></div>
          <div className="orb-ring ring-1"></div>
          <div className="orb-ring ring-2"></div>
          <div className="orb-ring ring-3"></div>
          <div className="orb-glow"></div>
        </div>

        {/* State Badge & Barge-in Controls */}
        <div className="orb-state-label">
          <span className={`state-badge ${state.toLowerCase()}`}>{state}</span>
          {state === "SPEAKING" && (
            <button className="interrupt-btn" onClick={triggerBargeIn}>
              ⚡ Barge-in / Interrupt
            </button>
          )}
        </div>

        {/* Live Audio Frequency Oscilloscope Canvas */}
        <canvas ref={canvasRef} className="waveform-canvas" width={380} height={44} />

        {/* Status / Speech Output Bubble */}
        <div className="voice-status-display">
          <p className="status-main-text">{spokenStatusText}</p>
        </div>

        {/* Live Speech Recognition Transcription Preview */}
        {liveTranscript && (
          <div className="live-transcript-bubble">
            <span className="transcript-icon">🎙️</span>
            <span className="transcript-text">{liveTranscript}</span>
          </div>
        )}
      </div>

      {/* Master Session Controls */}
      <div className="voice-controls-bar">
        {!isSessionActive ? (
          <button className="mic-primary-btn active" onClick={() => { void startVoiceSession(); }}>
            ▶ Start Voice Conversation
          </button>
        ) : (
          <button className="mic-primary-btn" onClick={stopVoiceSession} style={{ background: "#ff3366" }}>
            ⏹ Stop Voice Conversation
          </button>
        )}

        <button
          className="control-toggle"
          onClick={() => {
            if ("speechSynthesis" in window) {
              window.speechSynthesis.cancel();
            }
            if (isSessionActive) {
              triggerBargeIn();
            }
          }}
          title="Interrupt current audio"
        >
          Interrupt Speech
        </button>

        <button
          className="control-toggle"
          onClick={() => setShowLog(!showLog)}
        >
          {showLog ? "Hide Activity Log" : "Show Activity Log"}
        </button>

        {onSwitchToTextChat && (
          <button className="control-toggle" onClick={onSwitchToTextChat}>
            💬 Switch to Text Chat
          </button>
        )}
      </div>

      {/* Fast Voice Command Examples */}
      <div className="quick-actions-tray">
        <span className="quick-label">Try Speaking:</span>
        <button onClick={() => { void processVoiceUtterance("open chrome"); }}>"Open Chrome"</button>
        <button onClick={() => { void processVoiceUtterance("open camera"); }}>"Open Camera"</button>
        <button onClick={() => { void processVoiceUtterance("open calculator"); }}>"Open Calculator"</button>
        <button onClick={() => { void processVoiceUtterance("who am i"); }}>"Who am I?"</button>
        <button onClick={() => { void processVoiceUtterance("battery kitni hai"); }}>"Battery kitni hai?"</button>
        <button onClick={() => { void processVoiceUtterance("volume up"); }}>"Volume up"</button>
        <button onClick={() => { void processVoiceUtterance("open my latest pdf"); }}>"Open my latest PDF"</button>
        <button onClick={() => { void processVoiceUtterance("search for AI internships"); }}>"Search for AI internships"</button>
        <button onClick={() => { void processVoiceUtterance("stop listening"); }}>"Stop listening"</button>
      </div>

      {/* Optional Collapsible Activity Log */}
      {showLog && (
        <div className="voice-log-container">
          <div className="log-header">
            <span>Voice Session Activity Stream</span>
            <button className="clear-log-btn" onClick={() => setSessionLogs([])}>
              Clear
            </button>
          </div>
          <div className="log-entries">
            {sessionLogs.length === 0 ? (
              <div style={{ color: "#64748b", fontSize: "12px", textAlign: "center", padding: "10px" }}>
                No speech activity recorded yet.
              </div>
            ) : (
              sessionLogs.map((item) => (
                <div key={item.id} className={`log-entry ${item.sender}`}>
                  <div className="log-meta">
                    <span className="log-sender">{item.sender === "user" ? "You" : "KELA"}</span>
                    <span className="log-time">{item.time}</span>
                  </div>
                  <div className="log-text">{item.text}</div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
