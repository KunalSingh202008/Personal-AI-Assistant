import { useEffect, useRef, useState, useCallback } from "react";

export type VoiceState =
  | "IDLE"
  | "LISTENING"
  | "SPEECH_DETECTED"
  | "TRANSCRIBING"
  | "PROCESSING"
  | "EXECUTING"
  | "SPEAKING"
  | "INTERRUPTED"
  | "PAUSED"
  | "STOPPED"
  | "ERROR";

interface VoiceAssistantProps {
  apiUrl: string;
  onSwitchToTextChat?: () => void;
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
  const recognitionRef = useRef<any>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const silenceTimerRef = useRef<any>(null);
  const ttsSafetyTimerRef = useRef<any>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const transcriptBufferRef = useRef<string>("");
  const stateRef = useRef<VoiceState>("IDLE");
  const isSpeakingRef = useRef<boolean>(false);
  const isProcessingRef = useRef<boolean>(false);
  const isSessionActiveRef = useRef<boolean>(false);

  // Sync refs with state
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    isSessionActiveRef.current = isSessionActive;
  }, [isSessionActive]);

  // Fetch initial system telemetry
  useEffect(() => {
    fetch(`${apiUrl}/api/pc/system`)
      .then((r) => r.json())
      .then((data) => {
        if (data?.metrics) {
          setSystemMetrics({
            cpu: data.metrics.cpu_load_percent,
            ram_used: data.metrics.used_ram_mb,
            ram_free: data.metrics.free_ram_mb,
            battery: data.metrics.battery_percent,
          });
        }
      })
      .catch(() => {});
  }, [apiUrl]);

  // Setup Web Audio Analyser with Real-time Echo Cancellation
  const initAudioAnalyser = useCallback(async () => {
    try {
      if (!audioContextRef.current) {
        const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
        audioContextRef.current = new AudioContextClass();
      }
      if (audioContextRef.current.state === "suspended") {
        await audioContextRef.current.resume();
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

      const source = audioContextRef.current.createMediaStreamSource(mediaStreamRef.current);
      const analyser = audioContextRef.current.createAnalyser();
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

        // Active Barge-in check: If user speaks loudly while KELA is talking, cut speech immediately
        if (isSpeakingRef.current) {
          let energySum = 0;
          for (let i = 0; i < bufferLength; i++) {
            energySum += dataArray[i];
          }
          const avgEnergy = energySum / bufferLength;
          if (avgEnergy > 60) {
            triggerBargeIn();
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
            grad.addColorStop(1, "#00f0ff");
          } else if (stateRef.current === "SPEAKING") {
            grad.addColorStop(0, "#ffd700");
            grad.addColorStop(1, "#ff8800");
          } else {
            grad.addColorStop(0, "#00f0ff");
            grad.addColorStop(1, "#7928ca");
          }

          ctx.fillStyle = grad;
          ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
          x += barWidth + 2;
        }
      };

      drawWave();
    } catch (err) {
      console.warn("Waveform capture init failed:", err);
    }
  }, []);

  const releaseAudioAnalyser = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
  }, []);

  // Natural Spoken Speech (Text-To-Speech) with Fast Recovery
  const speakVoiceResponse = useCallback((text: string, lang = "english", shouldStopSession = false) => {
    if (!("speechSynthesis" in window)) {
      if (shouldStopSession) stopVoiceSession();
      else resumeListening();
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
      if (shouldStopSession) stopVoiceSession();
      else resumeListening();
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
        stopVoiceSession();
      } else if (isSessionActiveRef.current) {
        // AUTOMATICALLY RESUME LISTENING IMMEDIATELY!
        resumeListening();
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

    // Safety timeout: prevents Chrome's speech engine from ever locking up the assistant
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
        resumeListening();
      } else {
        setState("IDLE");
      }
    }, 150);
  }, []);

  // Process Completed Voice Utterance (Autonomous Backend Pipeline)
  const processVoiceUtterance = useCallback(
    async (utteranceText: string) => {
      if (!utteranceText.trim() || isProcessingRef.current) return;

      // Clear any pending timers
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }

      // 1. Instant transition to PROCESSING
      isProcessingRef.current = true;
      setState("PROCESSING");
      setLiveTranscript("");
      setSpokenStatusText(`Processing: "${utteranceText}"`);

      const timeStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      setSessionLogs((prev) => [
        ...prev,
        { id: String(Date.now()), sender: "user", text: utteranceText, time: timeStr },
      ]);

      // 2. Pause speech recognition capture during processing
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch {}
      }

      // 3. Dispatch to Unified KELA Voice Backend
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

        const result = await response.json();
        isProcessingRef.current = false;

        // Visual flash for tool execution
        if (result.action && !["greeting", "identity", "conversational_ai"].includes(result.action)) {
          setState("EXECUTING");
          setSpokenStatusText(`Executing: ${result.action}`);
          await new Promise((r) => setTimeout(r, 180));
        }

        // 4. Speak response aloud immediately!
        const responseText = result.response_text || "Done, Kunal.";
        speakVoiceResponse(responseText, result.lang || "english", Boolean(result.stop_session));
      } catch (err: any) {
        isProcessingRef.current = false;
        if (err.name === "AbortError") return;
        console.error("Voice processing error:", err);
        const errMsg = "I had trouble processing that command.";
        setState("ERROR");
        speakVoiceResponse(errMsg, "english", false);
      }
    },
    [apiUrl, speakVoiceResponse]
  );

  // Resume / Start Speech Recognition with Zero-Delay Finalizer
  const resumeListening = useCallback(() => {
    if (!isSessionActiveRef.current || isSpeakingRef.current || isProcessingRef.current) return;

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser. Please use Google Chrome or Microsoft Edge.");
      setState("ERROR");
      return;
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort();
      } catch {}
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-IN"; // Indian English & Hinglish support

    recognition.onstart = () => {
      setState("LISTENING");
      setSpokenStatusText("Listening to you...");
    };

    recognition.onspeechstart = () => {
      setState("SPEECH_DETECTED");
    };

    recognition.onresult = (event: any) => {
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
        processVoiceUtterance(finalStr.trim());
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
            processVoiceUtterance(textToSubmit);
          }
        }, 650);
      }
    };

    recognition.onerror = (event: any) => {
      if (event.error === "no-speech") return;
      console.warn("Speech recognition notice:", event.error);
    };

    recognition.onend = () => {
      if (isSessionActiveRef.current && !isSpeakingRef.current && !isProcessingRef.current) {
        try {
          recognition.start();
        } catch {}
      }
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch (e) {
      console.warn("Recognition start issue:", e);
    }
  }, [processVoiceUtterance]);

  // Start Voice Session
  const startVoiceSession = useCallback(async () => {
    setIsSessionActive(true);
    isSessionActiveRef.current = true;
    await initAudioAnalyser();
    resumeListening();
    setSpokenStatusText("Listening to you...");
  }, [initAudioAnalyser, resumeListening]);

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
      } catch {}
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

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      if (ttsSafetyTimerRef.current) clearTimeout(ttsSafetyTimerRef.current);
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {}
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
          onClick={state === "SPEAKING" ? triggerBargeIn : isSessionActive ? stopVoiceSession : startVoiceSession}
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
          <button className="mic-primary-btn active" onClick={startVoiceSession}>
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
        <button onClick={() => processVoiceUtterance("open chrome")}>"Open Chrome"</button>
        <button onClick={() => processVoiceUtterance("open camera")}>"Open Camera"</button>
        <button onClick={() => processVoiceUtterance("open calculator")}>"Open Calculator"</button>
        <button onClick={() => processVoiceUtterance("who am i")}>"Who am I?"</button>
        <button onClick={() => processVoiceUtterance("battery kitni hai")}>"Battery kitni hai?"</button>
        <button onClick={() => processVoiceUtterance("volume up")}>"Volume up"</button>
        <button onClick={() => processVoiceUtterance("open my latest pdf")}>"Open my latest PDF"</button>
        <button onClick={() => processVoiceUtterance("search for AI internships")}>"Search for AI internships"</button>
        <button onClick={() => processVoiceUtterance("stop listening")}>"Stop listening"</button>
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
