import { Anchor, Container, Group, Title } from "@mantine/core";
import { Link, Route, Routes } from "react-router-dom";

import ProjectPage from "./pages/ProjectPage";
import ProjectsPage from "./pages/ProjectsPage";
import RunsPage from "./pages/RunsPage";

export default function App() {
  return (
    <Container size="md" py="lg">
      <Group mb="lg">
        <Anchor component={Link} to="/" fw={700} underline="never">
          <Title order={3}>Аналитический центр</Title>
        </Anchor>
      </Group>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/projects/:id" element={<ProjectPage />} />
        <Route path="/projects/:id/runs" element={<RunsPage />} />
      </Routes>
    </Container>
  );
}
