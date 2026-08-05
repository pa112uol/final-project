interface PageHeaderProps {
  title: string;
}

// Names what the page is showing
export default function PageHeader({ title }: PageHeaderProps) {
  return (
    <h1 className="text-2xl font-extrabold tracking-[-0.02em] text-text-primary mb-[18px]">
      {title}
    </h1>
  );
}

