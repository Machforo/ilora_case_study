// src/components/chat-interface.tsx
import React, { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send, Bot, User, MessageCircle } from "lucide-react";
import ReactMarkdown from "react-markdown";


/**
 * Default API base — matches your main.py default.
 * Override with REACT_APP_API_BASE or NEXT_PUBLIC_API_BASE env var if needed.
 */
const API_BASE = "http://localhost:8000";

/* ---------------------- Helpers ---------------------- */
function isoDateOnly(d?: string | Date): string | null {
  if (!d) return null;
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return null;
  return dt.toISOString().slice(0, 10);
}

function nightsBetween(ci?: string | Date, co?: string | Date) {
  const a = new Date(String(ci));
  const b = new Date(String(co));
  if (isNaN(a.getTime()) || isNaN(b.getTime())) return 1;
  const diff = Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24));
  return Math.max(1, diff);
}

const formatTime = (date?: Date | string) => {
  if (!date) return "";
  const d = typeof date === "string" ? new Date(date) : date;
  if (!(d instanceof Date) || isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

function uuidv4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/* Parse FastAPI error responses intelligently */
async function parseErrorDetail(resp: Response): Promise<string> {
  const text = await resp.text();
  try {
    const j = JSON.parse(text);
    if (j?.detail) {
      if (Array.isArray(j.detail)) {
        return j.detail.map((d: any) => (d?.msg ? d.msg : JSON.stringify(d))).join("; ");
      }
      if (typeof j.detail === "string") return j.detail;
      return JSON.stringify(j.detail);
    }
    if (j?.message) return j.message;
    return JSON.stringify(j);
  } catch {
    return text;
  }
}

async function safeJson(resp: Response) {
  const text = await resp.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Non-JSON response (${resp.status}): ${text}`);
  }
}

/* ---------------------- Types ---------------------- */
interface Message {
  id: string;
  content: string;
  sender: "bot" | "user" | "system";
  timestamp: string;
  type?: "text" | "booking-form" | "booking-confirmation" | "pending-balance" | "addons";
  data?: any;
}

/* ---------------------- Booking Form ---------------------- */
function BookingForm({ onSubmit, initial }: { onSubmit: (d: any) => void; initial?: any }) {
  const [form, setForm] = useState({
    check_in: initial?.check_in || "",
    check_out: initial?.check_out || "",
    guest_name: initial?.guest_name || "",
    guest_phone: initial?.guest_phone || "",
    email: initial?.email || "",
    extras: initial?.extras || [],
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(form);
      }}
      className="space-y-3"
    >
      <Input
        type="date"
        value={form.check_in}
        onChange={(e) => setForm({ ...form, check_in: e.target.value })}
      />
      <Input
        type="date"
        value={form.check_out}
        onChange={(e) => setForm({ ...form, check_out: e.target.value })}
      />
      <Input
        placeholder="Full name"
        value={form.guest_name}
        onChange={(e) => setForm({ ...form, guest_name: e.target.value })}
      />
      <Input
        placeholder="Phone"
        value={form.guest_phone}
        onChange={(e) => setForm({ ...form, guest_phone: e.target.value })}
      />
      <Input
        placeholder="Email (optional)"
        value={form.email}
        onChange={(e) => setForm({ ...form, email: e.target.value })}
      />
      <div className="flex gap-2">
        <Button type="submit" className="flex-1">
          Confirm Booking
        </Button>
      </div>
    </form>
  );
}

/* ---------------------- Main Chat Component ---------------------- */
export function ChatInterface({ className }: { className?: string }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: `welcome-${Date.now()}`,
      content: "Hello! Welcome to ILORA RETREATS. I'm your concierge. How may I assist you today?",
      sender: "bot",
      timestamp: new Date().toISOString(),
      type: "text",
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [bookingProcessing, setBookingProcessing] = useState(false);
  const [email, setEmail] = useState<string>("");

  // refs (sessionId kept in ref to avoid re-renders)
  const sessionIdRef = useRef<string | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  /* Initialize client-only things (session id, saved email) */
  useEffect(() => {
    if (typeof window === "undefined") return;

    // session id
    try {
      const key = "illora_session_id";
      let s = localStorage.getItem(key);
      if (!s) {
        s = uuidv4();
        localStorage.setItem(key, s);
      }
      sessionIdRef.current = s;
    } catch (e) {
      // ignore localStorage errors (e.g., private mode)
      sessionIdRef.current = uuidv4();
    }

    // email
    try {
      const saved = localStorage.getItem("illora_email");
      if (saved) setEmail(saved);
    } catch {
      // ignore
    }
  }, []);

  /* SSE: connect to /events only on client */
  useEffect(() => {
    if (typeof window === "undefined") return;

    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/events`);
      eventSourceRef.current = es;

      es.onmessage = (evt) => {
        if (!evt.data) return;
        try {
          const parsed = JSON.parse(evt.data);
          const { event, data } = parsed as { event: string; data: any };

          if (event === "chat_message") {
            // Only append messages for this session ID to avoid duplicates across users
            if (!data || data.session_id !== sessionIdRef.current) return;
            if (!data.assistant) return;
            setMessages((prev) => {
              const exists = prev.some((m) => m.content === data.assistant && m.sender === "bot");
              if (exists) return prev;
              return [
                ...prev,
                {
                  id: `es-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                  content: data.assistant,
                  sender: "bot",
                  timestamp: new Date().toISOString(),
                  type: "text",
                },
              ];
            });
          } else if (event === "booking_confirmed") {
            setMessages((prev) => [
              ...prev,
              {
                id: `booking-confirmed-${Date.now()}`,
                content: "Your booking is ready for payment.",
                sender: "bot",
                timestamp: new Date().toISOString(),
                type: "booking-confirmation",
                data,
              },
            ]);
          } else if (event === "booking_created" || event === "booking_updated") {
            setMessages((prev) => [
              ...prev,
              {
                id: `booking-event-${Date.now()}-${event}`,
                content: `[${event}] ${JSON.stringify(data)}`,
                sender: "system",
                timestamp: new Date().toISOString(),
                type: "text",
                data,
              },
            ]);
          }
        } catch {
          // ignore
        }
      };

      es.onerror = (_e) => {
        // EventSource will auto-reconnect; do nothing.
      };
    } catch (e) {
      // EventSource may not be available / blocked
      console.warn("SSE init failed", e);
    }

    return () => {
      if (es) es.close();
      eventSourceRef.current = null;
    };
  }, []);

  /* Auto-scroll to bottom whenever messages/isTyping change */
  useEffect(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const scrollContainer = el.querySelector("[data-radix-scroll-area-viewport]") as HTMLElement | null;
    if (scrollContainer) {
      setTimeout(() => {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      }, 40);
    } else {
      // fallback
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, isTyping]);

  function addMessage(m: Message) {
    setMessages((prev) => [...prev, m]);
  }

  /* Send to /chat (matches ChatReq in main.py) */
  async function sendMessageToBackend(message: string) {
    const payload = {
      message,
      is_guest: true,
      session_id: sessionIdRef.current ?? uuidv4(),
      email: email || undefined,
    };

    const resp = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const errText = await parseErrorDetail(resp);
      throw new Error(errText || `Chat API returned ${resp.status}`);
    }
    const j = await safeJson(resp);
    return j;
  }
  

  const handleSendMessage = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const trimmed = inputValue.trim();
    if (!trimmed) return;

    const userMessage: Message = {
      id: `u-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      content: trimmed,
      sender: "user",
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setIsTyping(true);
    inputRef.current?.focus();

    try {
      const res = await sendMessageToBackend(trimmed);
      if (res?.reply) {
        addMessage({
          id: `b-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          content: res.reply,
          sender: "bot",
          timestamp: new Date().toISOString(),
          type: "text",
        });
      }

      if (res?.actions) {
        const actions = res.actions;
        if (actions.show_booking_form) {
          addMessage({
            id: `booking-form-${Date.now()}`,
            content: "Please share booking details:",
            sender: "system",
            timestamp: new Date().toISOString(),
            type: "booking-form",
          });
        }
        if (actions.payment_link) {
          addMessage({
            id: `payment-link-${Date.now()}`,
            content: "A payment link is available.",
            sender: "bot",
            timestamp: new Date().toISOString(),
            type: "booking-confirmation",
            data: { checkout_url: actions.payment_link },
          });
        }
        if (actions.addons && Array.isArray(actions.addons) && actions.addons.length > 0) {
          addMessage({
            id: `addons-${Date.now()}`,
            content: `I can add these extras for you: ${actions.addons.join(", ")}`,
            sender: "bot",
            timestamp: new Date().toISOString(),
            type: "addons",
            data: { addons: actions.addons },
          });
        }
        if (actions.pending_balance) {
          addMessage({
            id: `pending-${Date.now()}`,
            content: `You have a pending balance of ${actions.pending_balance.amount}.`,
            sender: "bot",
            timestamp: new Date().toISOString(),
            type: "pending-balance",
            data: actions.pending_balance,
          });
        }
      }
    } catch (err: any) {
      console.error("Chat API error:", err);
      addMessage({
        id: `err-${Date.now()}`,
        content: "⚠️ Error connecting to server. Please try again later.",
        sender: "bot",
        timestamp: new Date().toISOString(),
      });
    } finally {
      setIsTyping(false);
      inputRef.current?.focus();
    }
  };

  /* ---------------- Booking flow ---------------- */
  const handleBookingSubmit = async (formData: any) => {
    if (bookingProcessing) return;
    setBookingProcessing(true);
    setIsTyping(true);

    // save email locally if provided
    if (typeof window !== "undefined" && formData?.email) {
      try {
        localStorage.setItem("illora_email", formData.email);
        setEmail(formData.email);
      } catch {}
    }

    try {
      const check_in = isoDateOnly(formData.check_in || formData.checkIn);
      const check_out = isoDateOnly(formData.check_out || formData.checkOut);

      if (!check_in || !check_out) {
        addMessage({
          id: `err-dates-${Date.now()}`,
          content: "⚠️ Please provide valid check-in and check-out dates (YYYY-MM-DD).",
          sender: "bot",
          timestamp: new Date().toISOString(),
        });
        return;
      }
      if (new Date(check_out) < new Date(check_in)) {
        addMessage({
          id: `err-order-${Date.now()}`,
          content: "⚠️ Check-out must be same or after check-in.",
          sender: "bot",
          timestamp: new Date().toISOString(),
        });
        return;
      }

      const roomId = Number(formData.room_id || formData.selectedRoomId);
      if (!Number.isFinite(roomId) || roomId <= 0) {
        addMessage({
          id: `err-roomid-${Date.now()}`,
          content: "⚠️ Please provide a valid numeric Room ID.",
          sender: "bot",
          timestamp: new Date().toISOString(),
        });
        return;
      }

      const stagePayload = {
        room_id: roomId,
        check_in,
        check_out,
        guest_name: formData.guest_name || formData.guestName || "Guest",
        guest_phone: formData.guest_phone || formData.whatsapp_number || "",
      };

      // Stage booking
      const emailParam = encodeURIComponent(formData.email || email || "");
      const stageResp = await fetch(`${API_BASE}/bookings/stage?email=${emailParam}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(stagePayload),
      });

      if (!stageResp.ok) {
        const errText = await parseErrorDetail(stageResp);
        throw new Error(`Staging failed (${stageResp.status}): ${errText}`);
      }

      const staged = await safeJson(stageResp);
      if (!staged || !staged.booking_id) {
        throw new Error("Staging did not return booking_id");
      }

      const bookingId = String(staged.booking_id);
      const nights = nightsBetween(stagePayload.check_in, stagePayload.check_out);

      const confirmBody = {
        booking_id: bookingId,
        room_type: formData.room_type || formData.selectedRoomType || "",
        nights,
        cash: !!formData.cash || false,
        extras: formData.extras || [],
      };

      const confirmResp = await fetch(`${API_BASE}/bookings/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirmBody),
      });

      if (!confirmResp.ok) {
        const errText = await parseErrorDetail(confirmResp);
        throw new Error(`Confirm failed (${confirmResp.status}): ${errText}`);
      }

      const confirmed = await safeJson(confirmResp);
      addMessage({
        id: `confirmed-${Date.now()}`,
        content: `✅ Booking staged successfully. Click Pay to complete your booking.`,
        sender: "bot",
        timestamp: new Date().toISOString(),
        type: "booking-confirmation",
        data: confirmed,
      });
    } catch (err: any) {
      console.error("Booking error:", err);
      addMessage({
        id: `err-booking-${Date.now()}`,
        content: `⚠️ Failed to make booking: ${err?.message ?? String(err)}`,
        sender: "bot",
        timestamp: new Date().toISOString(),
      });
    } finally {
      setBookingProcessing(false);
      setIsTyping(false);
    }
  };

  /* ---------------- Addon / pending balance helpers ---------------- */
  async function createAddonCheckout(sessionId: string, extras: string[]) {
    // send POST with query params: /addons/checkout?session_id=...&extras=val&extras=val
    const url = new URL(`${API_BASE}/addons/checkout`);
    url.searchParams.append("session_id", sessionId);
    extras.forEach((x) => url.searchParams.append("extras", x));
    const resp = await fetch(url.toString(), { method: "POST" });
    if (!resp.ok) {
      const errText = await parseErrorDetail(resp);
      throw new Error(`Addon checkout failed (${resp.status}): ${errText}`);
    }
    const j = await safeJson(resp);
    if (j?.checkout_url) return j.checkout_url;
    return null;
  }

  async function payPendingBalance(amount: number) {
    try {
      const resp = await fetch(`${API_BASE}/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount }),
      });
      if (!resp.ok) {
        const errText = await parseErrorDetail(resp);
        throw new Error(`Payment creation failed: ${errText}`);
      }
      const j = await safeJson(resp);
      const url = j?.checkout_url ?? (typeof j === "string" ? j : null);
      if (url) window.open(url, "_blank");
    } catch (e) {
      console.error("payPendingBalance error", e);
      addMessage({
        id: `err-pay-${Date.now()}`,
        content: `⚠️ Failed to initiate payment: ${String(e)}`,
        sender: "bot",
        timestamp: new Date().toISOString(),
      });
    }
  }

  /* ---------------- UI ---------------- */
  return (
    <div className={`flex flex-col h-full ${className || ""}`}>
      <div className="px-4 pt-3 flex items-center gap-3">
        <div className="text-lg font-semibold">ILORA Retreats Concierge</div>
        <div className="text-sm text-muted-foreground">Session: {sessionIdRef.current?.slice(0, 8) ?? "—"}</div>
        <div className="ml-auto">
          <Input
            placeholder="Email (optional)"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (typeof window !== "undefined") {
                try {
                  localStorage.setItem("illora_email", e.target.value);
                } catch {}
              }
            }}
            className="h-8 text-sm"
          />
        </div>
      </div>

      <ScrollArea ref={scrollAreaRef} className="flex-1 p-4 overflow-auto">
        <div className="space-y-4">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex items-start gap-3 ${message.sender === "user" ? "justify-end" : "justify-start"}`}
            >
              {message.sender === "bot" && (
                <div className="w-8 h-8 bg-hotel-primary rounded-full flex items-center justify-center flex-shrink-0">
                  <Bot className="w-4 h-4 text-white" />
                </div>
              )}

              <div className={`max-w-[70%] rounded-2xl px-4 py-3 ${message.sender === "bot" ? "bg-chat-bot border border-chat-border" : "bg-chat-user border border-hotel-success/20"}`}>
                {message.type === "booking-form" ? (
                  <BookingForm onSubmit={handleBookingSubmit} initial={{ email }} />
                ) : message.type === "booking-confirmation" && message.data ? (
                  <div>
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown>{message.content}</ReactMarkdown>
                    </div>
                    <div className="mt-3 flex gap-2">
                      {message.data.checkout_url && (
                        <Button onClick={() => window.open(message.data.checkout_url, "_blank")}>Pay Now</Button>
                      )}
                      {message.data.qr_url && (
                        <Button onClick={() => window.open(message.data.qr_url, "_blank")} variant="outline">
                          View QR
                        </Button>
                      )}
                    </div>
                  </div>
                ) : message.type === "pending-balance" && message.data ? (
                  <div>
                    <div className="text-sm font-medium">Pending Balance</div>
                    <div className="text-xs mt-2">Amount: {message.data.amount ?? "N/A"}</div>
                    {Array.isArray(message.data.items) && (
                      <ul className="mt-2 text-sm list-disc pl-4">
                        {message.data.items.map((it: any, idx: number) => (
                          <li key={idx}>{it.description ?? JSON.stringify(it)}</li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-3">
                      <Button onClick={() => payPendingBalance(message.data.amount ?? 0)}>Pay Pending Balance</Button>
                    </div>
                  </div>
                ) : message.type === "addons" && message.data ? (
                  <div>
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown>{message.content}</ReactMarkdown>
                    </div>
                    <div className="mt-2 flex gap-2 flex-wrap">
                      {(message.data.addons || []).map((ad: string, i: number) => (
                        <Button
                          key={i}
                          onClick={async () => {
                            try {
                              const sessionId = sessionIdRef.current ?? uuidv4();
                              const url = await createAddonCheckout(sessionId, [ad]);
                              if (url) window.open(url, "_blank");
                              else
                                addMessage({
                                  id: `err-addon-${Date.now()}`,
                                  content: "⚠️ Failed to create addon checkout link.",
                                  sender: "bot",
                                  timestamp: new Date().toISOString(),
                                });
                            } catch (e) {
                              addMessage({
                                id: `err-addon-${Date.now()}`,
                                content: `⚠️ Addon checkout error: ${String(e)}`,
                                sender: "bot",
                                timestamp: new Date().toISOString(),
                              });
                            }
                          }}
                        >
                          Order {ad}
                        </Button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  </div>
                )}

                <p className="text-xs text-muted-foreground mt-2">{formatTime(message.timestamp)}</p>
              </div>

              {message.sender === "user" && (
                <div className="w-8 h-8 bg-hotel-success rounded-full flex items-center justify-center flex-shrink-0">
                  <User className="w-4 h-4 text-white" />
                </div>
              )}
            </div>
          ))}

          {isTyping && (
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 bg-hotel-primary rounded-full flex items-center justify-center">
                <Bot className="w-4 h-4 text-white" />
              </div>
              <div className="bg-chat-bot border border-chat-border rounded-2xl px-4 py-3">
                <div className="flex space-x-1">
                  <div className="w-2 h-2 bg-muted-foreground rounded-full animate-pulse"></div>
                  <div className="w-2 h-2 bg-muted-foreground rounded-full animate-pulse" style={{ animationDelay: "0.2s" }}></div>
                  <div className="w-2 h-2 bg-muted-foreground rounded-full animate-pulse" style={{ animationDelay: "0.4s" }}></div>
                </div>
              </div>
            </div>
          )}
        </div>
      </ScrollArea>

      <div className="p-4 border-t border-chat-border bg-background">
        <form onSubmit={handleSendMessage} className="flex gap-2">
          <Input
            ref={(el) => (inputRef.current = el)}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Ask me anything about ILORA Retreats..."
            className="flex-1 h-12 rounded-full px-4"
            disabled={isTyping}
          />
          <Button
            type="submit"
            size="lg"
            className="h-12 w-12 rounded-full bg-gradient-primary hover:opacity-90 transition-opacity"
            disabled={!inputValue.trim() || isTyping}
          >
            <Send className="w-5 h-5" />
          </Button>
        </form>
      </div>

      <div className="p-4 pt-0">
        <Button
          variant="outline"
          size="lg"
          className="w-full h-12 border-hotel-success/20 text-hotel-success hover:bg-hotel-success/5"
          onClick={() => {
            if (typeof window !== "undefined") window.open("https://scan.page/D7EIyr", "_blank");
          }}
        >
          <MessageCircle className="w-5 h-5 mr-2" />
          Continue chat on WhatsApp
        </Button>
      </div>
    </div>
  );
}
