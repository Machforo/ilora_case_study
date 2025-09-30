import React, { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { WhatsAppQR } from "@/components/whatsapp-qr";
import { Building2, LogOut, MessageCircle, CreditCard, IdCard } from "lucide-react";

interface HotelSidebarProps {
  onLogout: () => void;
}

export function HotelSidebar({ onLogout }: HotelSidebarProps) {
  const [latestSession, setLatestSession] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = "http://localhost:8000";

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();

    async function fetchSessions() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/auth/sessions`, {
          method: "GET",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`Failed to fetch sessions: ${res.status}`);
        const payload = await res.json();
        if (!mounted) return;

        const sessions = Object.values(payload.sessions || {}) as any[];

        if (sessions.length > 0) {
          // sort by last_login
          const sorted = sessions.sort((a, b) => {
            const t1 = new Date(a.last_login || 0).getTime();
            const t2 = new Date(b.last_login || 0).getTime();
            return t1 - t2; // ascending
          });

          const latest = sorted.at(-1) || null;
          setLatestSession(latest);
          console.debug("Latest session chosen:", latest);
        } else {
          setLatestSession(null);
        }
      } catch (err: any) {
        if (!mounted) return;
        console.error("Error fetching sessions", err);
        setError(err?.message || String(err));
      } finally {
        if (mounted) setLoading(false);
      }
    }

    fetchSessions();
    return () => {
      mounted = false;
      controller.abort();
    };
  }, []);

  const sidebarData = useMemo(() => {
    if (!latestSession) {
      return {
        uid: "-",
        bookingStatus: "Not Booked",
        roomNumber: "-",
        idProof: "Not Verified",
        bookingId: "-",
        name: "-",
        pendingBalance: 0,
      };
    }

    // Merge frontend + normalized into a flat object
    const merged = { ...latestSession.normalized, ...latestSession.frontend };

    return {
      uid: merged.uid || merged.client_id || "-",
      bookingStatus: merged.bookingStatus || merged.status || merged.workflow_stage || "Not Booked",
      roomNumber: merged.roomNumber || merged.room_alloted || "-",
      idProof: merged.idProof || merged.id_link
        ? ["done", "verified"].includes(String(merged.idProof || merged.id_link).toLowerCase())
          ? "Verified"
          : "Not Verified"
        : "Not Verified",
      bookingId: merged.bookingId || merged.booking_id || "-",
      name: merged.name || "-",
      pendingBalance: merged.pendingBalance ?? merged.pending_balance ?? 0,
    };
  }, [latestSession]);

  function badgeVariantForBookingStatus(status: string) {
    const s = String(status || "").toLowerCase();
    if (s === "confirmed" || s === "done") return "default";
    if (s === "not done" || s === "pending") return "secondary";
    return "outline";
  }

  function formatINR(amount: number | string) {
    const n = Number(amount || 0);
    try {
      return `₹${n.toFixed(2)}`;
    } catch {
      return `₹${String(amount)}`;
    }
  }

  return (
    <div className="w-80 bg-background border-r border-chat-border h-screen flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-chat-border">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-gradient-primary rounded-lg flex items-center justify-center">
            <Building2 className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-hotel-primary">ILORA</h1>
            <p className="text-sm text-muted-foreground">Retreats</p>
          </div>
        </div>
      </div>

      {/* User Details */}
      <Card className="mx-4 mb-4 shadow-soft">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Your Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading && <div className="text-sm text-muted-foreground">Loading...</div>}
          {error && <div className="text-sm text-rose-600">Error: {error}</div>}

          {!loading && !error && (
            <>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">UID:</span>
                <Badge variant="outline" className="font-mono text-xs">
                  {sidebarData.uid}
                </Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground flex items-center gap-1">
                  <CreditCard className="w-3 h-3" />
                  Booking:
                </span>
                <Badge variant={badgeVariantForBookingStatus(sidebarData.bookingStatus)}>
                  {sidebarData.bookingStatus}
                </Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground flex items-center gap-1">
                  <Building2 className="w-3 h-3" />
                  Room:
                </span>
                <Badge variant="outline">{sidebarData.roomNumber}</Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground flex items-center gap-1">
                  <IdCard className="w-3 h-3" />
                  ID Proof:
                </span>
                <Badge variant={sidebarData.idProof === "Verified" ? "default" : "destructive"}>
                  {sidebarData.idProof}
                </Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Booking ID:</span>
                <Badge variant="outline" className="font-mono text-xs">
                  {sidebarData.bookingId}
                </Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Name:</span>
                <span className="text-sm">{sidebarData.name}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Pending Balance:</span>
                <span className="text-sm font-mono">{formatINR(sidebarData.pendingBalance)}</span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* WhatsApp */}
      <Card className="mx-4 mb-4 shadow-soft">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <MessageCircle className="w-5 h-5" />
            Connect on WhatsApp
          </CardTitle>
        </CardHeader>
        <CardContent className="text-center">
          <WhatsAppQR />
          <p className="text-xs text-muted-foreground mb-3">
            Scan QR code to chat with us on WhatsApp
          </p>
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => window.open("https://scan.page/D7EIyr", "_blank")}
          >
            <MessageCircle className="w-4 h-4 mr-2" />
            Chat with us on WhatsApp
          </Button>
        </CardContent>
      </Card>

      {/* Logout */}
      <div className="mt-auto p-4">
        <Button onClick={onLogout} variant="outline" className="w-full" size="lg">
          <LogOut className="w-4 h-4 mr-2" />
          Logout & Forget this device
        </Button>
      </div>
    </div>
  );
}

export default HotelSidebar;
