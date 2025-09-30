import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { HotelSidebar } from "@/components/hotel-sidebar";
import { HeroSection } from "@/components/hero-section";
import { ChatInterface } from "@/components/chat-interface";
import { Menu } from "lucide-react";

interface MobileLayoutProps {
  onLogout: () => void;
  userDetails?: {
    uid: string;
    bookingStatus: string;
    idProof: string;
    pendingBalance: number;
    status: string;
  };
}

export function MobileLayout({ onLogout, userDetails }: MobileLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-hotel-light flex flex-col">
      {/* Mobile Header */}
      <div className="bg-background border-b border-chat-border p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-primary rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-sm">I</span>
          </div>
          <div>
            <h1 className="font-bold text-hotel-primary">ILORA Retreats</h1>
            <p className="text-xs text-muted-foreground">AI Concierge</p>
          </div>
        </div>
        
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm">
              <Menu className="w-4 h-4" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0 w-80">
            <HotelSidebar
              onLogout={onLogout}
              userDetails={userDetails}
            />
          </SheetContent>
        </Sheet>
      </div>

      {/* Hero Section - Compact on Mobile */}
      <div className="p-4">
        <div className="relative h-48 overflow-hidden rounded-lg shadow-medium">
          <div className="absolute inset-0 bg-gradient-hero" />
          <div className="relative z-10 flex flex-col items-center justify-center h-full text-center text-white p-4">
            <h1 className="text-2xl font-bold mb-2">
              🏨 ILORA Retreats
            </h1>
            <p className="text-sm opacity-90">
              Your AI Concierge
            </p>
          </div>
        </div>
      </div>

      {/* Chat Interface */}
      <div className="flex-1 mx-4 mb-4">
        <div className="bg-background rounded-lg shadow-soft h-full">
          <ChatInterface />
        </div>
      </div>
    </div>
  );
}