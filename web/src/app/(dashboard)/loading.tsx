export default function Loading() {
  return <div aria-hidden="true" className="route-skeleton">
    <div className="skeleton skeleton-heading" />
    <div className="skeleton-metrics">
      {[0, 1, 2].map((index) => <div className="skeleton skeleton-metric" key={index} />)}
    </div>
    <div className="skeleton skeleton-surface" />
  </div>;
}
