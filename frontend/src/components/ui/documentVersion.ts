export function documentVersionFromFilename(filename: string) {
  const basename = filename.replaceAll("\\", "/").split("/").at(-1);
  const stem = (basename ?? "").replace(/\.[^.]*$/, "");
  const versions = [
    ...stem.matchAll(
      /(?:^|[^A-Za-z0-9])v([0-9]+\.[0-9]+(?:\.[0-9]+)*)(?![A-Za-z0-9.])/gi,
    ),
  ];
  return versions.at(-1)?.[1] ?? "1.0";
}
