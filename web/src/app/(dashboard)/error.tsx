"use client";
export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) { return <section className="route-panel error-state" role="alert"><p className="eyebrow">Unexpected UI error</p><h1>Something went wrong</h1><p>The page could not render this response safely.</p><button type="button" onClick={() => reset()}>Try again</button></section>; }
