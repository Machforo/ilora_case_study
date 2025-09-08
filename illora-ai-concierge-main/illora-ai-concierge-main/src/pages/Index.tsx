import { useState, useEffect } from "react";
import { LoginForm } from "@/components/ui/login-form";
import { HotelSidebar } from "@/components/hotel-sidebar";
import { ChatInterface } from "@/components/chat-interface";
import { HeroSection } from "@/components/hero-section";
import { MobileLayout } from "@/components/mobile-layout";
import { useToast } from "@/hooks/use-toast";
import { useIsMobile } from "@/hooks/use-mobile";

const Index = () => {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [isGuest, setIsGuest] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();
  const isMobile = useIsMobile();

  // Check for saved login state on component mount
  useEffect(() => {
    const savedLogin = localStorage.getItem("illora-logged-in");
    const savedGuestStatus = localStorage.getItem("illora-guest-status");
    
    if (savedLogin === "true") {
      setIsLoggedIn(true);
    }
    if (savedGuestStatus === "true") {
      setIsGuest(true);
    }
  }, []);

  const handleLogin = async (credentials: { email: string; password: string }) => {
    setIsLoading(true);
    
    // Simulate login process
    setTimeout(() => {
      // For demo purposes, accept any email/password
      localStorage.setItem("illora-logged-in", "true");
      setIsLoggedIn(true);
      setIsLoading(false);
      
      toast({
        title: "Welcome to ILLORA Retreat!",
        description: "You have successfully signed in to your AI concierge.",
      });
    }, 1000);
  };

  const handleLogout = () => {
    localStorage.removeItem("illora-logged-in");
    localStorage.removeItem("illora-guest-status");
    setIsLoggedIn(false);
    setIsGuest(false);
    
    toast({
      title: "Logged out successfully",
      description: "Your session has been cleared from this device.",
    });
  };

  const handleGuestStatusChange = (status: boolean) => {
    setIsGuest(status);
    localStorage.setItem("illora-guest-status", status.toString());
  };

  // Mock user details
  const userDetails = {
    uid: "ILR-2024-001",
    bookingStatus: "Confirmed",
    idProof: "Verified",
    pendingBalance: 0,
  };

  if (!isLoggedIn) {
    return <LoginForm onLogin={handleLogin} isLoading={isLoading} />;
  }

  // Mobile Layout
  if (isMobile) {
    return (
      <MobileLayout
        isGuest={isGuest}
        onGuestStatusChange={handleGuestStatusChange}
        onLogout={handleLogout}
        userDetails={userDetails}
      />
    );
  }

  // Desktop Layout
  return (
    <div className="min-h-screen bg-hotel-light flex">
      {/* Sidebar */}
      <HotelSidebar
        isGuest={isGuest}
        onGuestStatusChange={handleGuestStatusChange}
        onLogout={handleLogout}
        userDetails={userDetails}
      />

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Hero Section */}
        <div className="p-6">
          <HeroSection />
        </div>

        {/* Chat Interface */}
        <div className="flex-1 mx-6 mb-6">
          <div className="bg-background rounded-lg shadow-soft h-full">
            <ChatInterface />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Index;
