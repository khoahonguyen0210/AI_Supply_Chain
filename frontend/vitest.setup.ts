import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// findBy* waits 1 s by default, too short when the machine is busy.
configure({ asyncUtilTimeout: 5_000 });

afterEach(() => {
  cleanup();
});
