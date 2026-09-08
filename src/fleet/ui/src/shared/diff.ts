/**
 * Line diff between two text snapshots.
 * Moved out of features/task-detail/tabs/LiveTab.tsx so it can be unit
 * tested. Called by LiveTab's DiffView; tested by diff.test.ts.
 */

export interface DiffLine {
  type: 'equal' | 'remove' | 'add';
  text: string;
}

const MAX_LINES = 400;

// Split text into lines, treating empty input as zero lines.
function splitLines(text: string): string[] {
  return text === '' ? [] : text.split('\n');
}

// Pair every old line as removed and every new line as added.
function flatDiff(oldLines: string[], newLines: string[]): DiffLine[] {
  return [
    ...oldLines.map((text) => ({ type: 'remove' as const, text })),
    ...newLines.map((text) => ({ type: 'add' as const, text })),
  ];
}

// Longest-common-subsequence table for the line arrays.
function lcsTable(oldLines: string[], newLines: string[]): number[][] {
  const dp: number[][] = Array.from({ length: oldLines.length + 1 }, () =>
    new Array(newLines.length + 1).fill(0),
  );
  for (let i = 1; i <= oldLines.length; i++) {
    for (let j = 1; j <= newLines.length; j++) {
      dp[i][j] =
        oldLines[i - 1] === newLines[j - 1]
          ? dp[i - 1][j - 1] + 1
          : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  return dp;
}

// Walk the LCS table back to an ordered line diff.
function backtrack(dp: number[][], oldLines: string[], newLines: string[]): DiffLine[] {
  const result: DiffLine[] = [];
  let i = oldLines.length;
  let j = newLines.length;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      result.unshift({ type: 'equal', text: oldLines[i - 1] });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({ type: 'add', text: newLines[j - 1] });
      j--;
    } else {
      result.unshift({ type: 'remove', text: oldLines[i - 1] });
      i--;
    }
  }
  return result;
}

// Diff two texts line by line (LCS; falls back to flat remove+add past MAX_LINES).
export function computeLineDiff(oldStr: string, newStr: string): DiffLine[] {
  const oldLines = splitLines(oldStr);
  const newLines = splitLines(newStr);
  if (oldLines.length > MAX_LINES || newLines.length > MAX_LINES) {
    return flatDiff(oldLines, newLines);
  }
  return backtrack(lcsTable(oldLines, newLines), oldLines, newLines);
}
