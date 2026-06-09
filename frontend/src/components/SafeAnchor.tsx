import { safeHref } from '../lib/utils';

type Props = React.AnchorHTMLAttributes<HTMLAnchorElement> & {
  href?: string | null;
};

export default function SafeAnchor({ href, children, ...rest }: Props) {
  const safe = safeHref(href);
  if (!safe) return <>{children}</>;
  return (
    <a href={safe} target="_blank" rel="noreferrer" {...rest}>
      {children}
    </a>
  );
}
