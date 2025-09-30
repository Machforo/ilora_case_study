import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface SignupFormProps {
  onSignup: (credentials: { name: string; email: string; password: string }) => void;
  isLoading: boolean;
  onSwitch: () => void; // switch back to login
}

export const SignupForm = ({ onSignup, isLoading, onSwitch }: SignupFormProps) => {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phoneNo, setPhoneNo] = useState("");
  const [password, setPassword] = useState("");


  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !email || !phoneNo || !password) return;
    onSignup({ name, email, phoneNo, password });
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-hotel-light">
      <form
        onSubmit={handleSubmit}
        className="bg-white shadow-soft rounded-lg p-8 w-full max-w-md space-y-4"
      >
        <h2 className="text-2xl font-semibold text-center">Create an Account</h2>

        <Input
          type="text"
          placeholder="Full Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <Input
          type="email"
          placeholder="Email Address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <Input
          type="Phone Number"
          placeholder="Phone Number"
          value={phoneNo}
          onChange={(e) => setPhoneNo(e.target.value)}
        />

        <Input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />



        <Button type="submit" disabled={isLoading} className="w-full">
          {isLoading ? "Creating Account..." : "Sign Up"}
        </Button>

        <p className="text-sm text-center text-gray-600">
          Already have an account?{" "}
          <button
            type="button"
            onClick={onSwitch}
            className="text-primary font-medium hover:underline"
          >
            Log in
          </button>
        </p>
      </form>
    </div>
  );
};
