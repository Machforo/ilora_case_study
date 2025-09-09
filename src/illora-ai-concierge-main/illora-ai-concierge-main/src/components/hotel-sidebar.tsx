import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { WhatsAppQR } from "@/components/whatsapp-qr";
import { Building2, LogOut, MessageCircle, User, CreditCard, IdCard } from "lucide-react";

interface HotelSidebarProps {
  isGuest: boolean;
  onGuestStatusChange: (isGuest: boolean) => void;
  onLogout: () => void;
  userDetails?: {
    uid: string;
    bookingStatus: string;
    idProof: string;
    pendingBalance: number;
  };
}

export function HotelSidebar({ isGuest, onGuestStatusChange, onLogout, userDetails }: HotelSidebarProps) {
  return (
    <div className="w-80 bg-background border-r border-chat-border h-screen flex flex-col">
      {/* Hotel Logo */}
      <div className="p-6 border-b border-chat-border">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-gradient-primary rounded-lg flex items-center justify-center">
            <Building2 className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-hotel-primary">ILLORA</h1>
            <p className="text-sm text-muted-foreground">Retreat</p>
          </div>
        </div>
      </div>

      {/* Guest Status */}
      <Card className="m-4 shadow-soft">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <User className="w-5 h-5" />
            Guest Status
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="guest-status" className="text-sm font-medium">
              Are you staying at ILLORA Retreat?
            </Label>
          </div>
          <div className="flex items-center space-x-2">
            <Switch
              id="guest-status"
              checked={isGuest}
              onCheckedChange={onGuestStatusChange}
            />
            <Label htmlFor="guest-status" className="text-sm">
              {isGuest ? "Yes" : "No"}
            </Label>
          </div>
        </CardContent>
      </Card>

      {/* User Details */}
      {userDetails && (
        <Card className="mx-4 mb-4 shadow-soft">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Your Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">UID:</span>
              <Badge variant="outline" className="font-mono text-xs">
                {userDetails.uid}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <CreditCard className="w-3 h-3" />
                Booking:
              </span>
              <Badge variant={userDetails.bookingStatus === "Confirmed" ? "default" : "secondary"}>
                {userDetails.bookingStatus}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <IdCard className="w-3 h-3" />
                ID Proof:
              </span>
              <Badge variant="outline">{userDetails.idProof}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Balance:</span>
              <Badge variant={userDetails.pendingBalance > 0 ? "destructive" : "default"}>
                ${userDetails.pendingBalance}
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}

      {/* WhatsApp Connection */}
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
            onClick={() => {
              window.open("https://scan.page/D7EIyr", "_blank");
            }}
          >
            <MessageCircle className="w-4 h-4 mr-2" />
            Chat with us on WhatsApp
          </Button>
        </CardContent>
      </Card>

      {/* Logout Button */}
      <div className="mt-auto p-4">
        <Button
          onClick={onLogout}
          variant="outline"
          className="w-full"
          size="lg"
        >
          <LogOut className="w-4 h-4 mr-2" />
          Logout & Forget this device
        </Button>
      </div>
    </div>
  );
}
