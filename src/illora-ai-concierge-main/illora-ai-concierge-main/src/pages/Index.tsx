import { useState, useEffect } from "react";
import { LoginForm } from "@/components/ui/login-form";
import { SignupForm } from "@/components/ui/SignupForm";
import { HotelSidebar } from "@/components/hotel-sidebar";
import { ChatInterface } from "@/components/chat-interface";
import { HeroSection } from "@/components/hero-section";
import { MobileLayout } from "@/components/mobile-layout";
import { useToast } from "@/hooks/use-toast";
import { useIsMobile } from "@/hooks/use-mobile";
import { API_BASE } from "@/lib/config";

const Index = () => {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSignUp, setIsSignUp] = useState(false);
  const [userData, setUserData] = useState<any>(null);

  const { toast } = useToast();
  const isMobile = useIsMobile();

  // Restore session and load user data
  useEffect(() => {
    const restoreSession = async () => {
      const savedLogin = localStorage.getItem("illora-logged-in");
      const savedUsername = localStorage.getItem("illora-username");
      
      if (savedLogin === "true" && savedUsername) {
        setIsLoading(true);
        try {
          // Re-fetch user data from Google Sheet
          const payload = {
            username: savedUsername,
          };
          const res = await fetch(`${API_BASE}/auth/me`, {
            method: "POST",
            body: JSON.stringify(payload),
            headers: { "Content-Type": "application/json" },
          });
          const data = await res.json();
          if (res.ok && data.userData) {
            setUserData(data.userData);
            setIsLoggedIn(true);
          } else {
            // Session invalid, clear storage
            localStorage.removeItem("illora-logged-in");
            localStorage.removeItem("illora-username");
            setIsLoggedIn(false);
            toast({
              title: "Session expired",
              description: "Please login again.",
              variant: "destructive",
            });
          }
        } catch (err) {
          console.error("Failed to restore session:", err);
          toast({
            title: "Connection error",
            description: "Could not restore your session.",
            variant: "destructive",
          });
        }
        setIsLoading(false);
      }
    };

    restoreSession();
  }, [toast]);

  // --- LOGIN ---
  const handleLogin = async (credentials: { email: string; password: string }) => {
    setIsLoading(true);
    try {
      const payload = {
        username: credentials.email, // Map email to username for backend
        password: credentials.password,
        remember: true,
      };
      console.log("Sending login request to:", `${API_BASE}/auth/login`);
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (res.ok && data.username) {
        localStorage.setItem("illora-logged-in", "true");
        localStorage.setItem("illora-username", data.username);
        setUserData(data.userData);
        setIsLoggedIn(true);
        toast({
          title: "Welcome to ILORA Retreats!",
        });
      } else {
        toast({
          title: "Login failed",
          description: data.message || "Invalid email or password.",
          variant: "destructive",
        });
      }
    } catch (err) {
      console.error(err);
      toast({
        title: "Error",
        description: "Could not connect to login service.",
        variant: "destructive",
      });
    }
    setIsLoading(false);
  };

  // --- SIGNUP ---
  const handleSignup = async (credentials: { name: string; email: string; phoneNo: string; password: string }) => {
    setIsLoading(true);
    try {
      // Map email to username for backend
      const payload = {
        name: credentials.name,
        username: credentials.email,
        password: credentials.password,
        phoneNo: credentials.phoneNo,
      };
      console.log("Sending signup request to:", `${API_BASE}/auth/signup`);
      const res = await fetch(`${API_BASE}/auth/signup`, {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (data.success) {
        toast({
          title: "Account created",
          description: "You can now login with your credentials.",
        });
        setIsSignUp(false);
      } else {
        toast({
          title: "Signup failed",
          description: data.message || "Try again later.",
          variant: "destructive",
        });
      }
    } catch (err) {
      console.error(err);
      toast({
        title: "Error",
        description: "Could not connect to signup service.",
        variant: "destructive",
      });
    }
    setIsLoading(false);
  };

  // --- LOGOUT ---
  const handleLogout = () => {
    localStorage.removeItem("illora-logged-in");
    localStorage.removeItem("illora-username");
    setIsLoggedIn(false);
    setUserData(null);

    toast({
      title: "Logged out successfully",
      description: "Your session has been cleared from this device.",
    });
  };

  // Map sheet data to user details
  const userDetails = userData ? {
    uid: userData["Client Id"] || "",
    bookingStatus: userData["Booking Id"] ? "Booked" : "Not Booked",
    idProof: userData["Id Link"] ? "Verified" : "Not Verified",
    pendingBalance: 0,  // This will need to be updated when payment system is integrated
    status: userData["Workfow Stage"] || "Still", // Fixed typo in field name from Google Sheet
    roomNumber: userData["Room Alloted"] || "",
    checkIn: userData["CheckIn"] || "",
    checkOut: userData["Check Out"] || "",
  } : undefined;

  // Debug logging to help diagnose data mapping issues
  console.log("Google Sheet User Data:", userData);
  console.log("Mapped User Details:", userDetails);

  // --- RENDER ---

  if (!isLoggedIn) {
    return isSignUp ? (
      <SignupForm
        onSignup={handleSignup}
        isLoading={isLoading}
        onSwitch={() => setIsSignUp(false)}
      />
    ) : (
      <LoginForm
        onLogin={handleLogin}
        isLoading={isLoading}
        onSwitch={() => setIsSignUp(true)}
      />
    );
  }

  // Mobile Layout
  if (isMobile) {
    return (
      <MobileLayout
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
