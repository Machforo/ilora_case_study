import heroImage from "@/assets/illora-retreat-hero.jpg";

export function HeroSection() {
  return (
    <div className="relative h-80 overflow-hidden rounded-lg shadow-medium">
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat"
        style={{ backgroundImage: `url(${heroImage})` }}
      />
      <div className="absolute inset-0 bg-gradient-hero" />
      <div className="relative z-10 flex flex-col items-center justify-center h-full text-center text-white p-8">
        <h1 className="text-4xl md:text-5xl font-bold mb-4">
          🏨 ILORA Retreats – Your AI Concierge
        </h1>
        <p className="text-lg md:text-xl opacity-90 max-w-2xl">
          Welcome to ILORA Retreats, where luxury meets the wilderness.
        </p>
      </div>
    </div>
  );
}