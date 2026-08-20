import unittest

from update_readme import replace_block, stars_badge_line


class TestReplaceBlock(unittest.TestCase):
    def test_replaces_content_between_markers(self):
        content = (
            "before\n"
            "<!-- BLOG:START -->\n"
            "old content\n"
            "<!-- BLOG:END -->\n"
            "after\n"
        )
        result = replace_block(content, "BLOG", ["- new item"])
        self.assertIn("- new item", result)
        self.assertNotIn("old content", result)
        self.assertTrue(result.startswith("before\n"))
        self.assertTrue(result.endswith("after\n"))

    def test_only_touches_matching_marker(self):
        content = (
            "<!-- BLOG:START -->\nblog\n<!-- BLOG:END -->\n"
            "<!-- ACTIVITY:START -->\nactivity\n<!-- ACTIVITY:END -->\n"
        )
        result = replace_block(content, "BLOG", ["- updated"])
        self.assertIn("- updated", result)
        self.assertIn("activity", result)  # untouched

    def test_missing_markers_raises(self):
        with self.assertRaises(RuntimeError):
            replace_block("no markers here", "BLOG", ["- x"])

    def test_empty_content_between_adjacent_markers(self):
        content = "<!-- BLOG:START -->\n<!-- BLOG:END -->\n"
        result = replace_block(content, "BLOG", ["- first post"])
        self.assertIn("- first post", result)

    def test_backslash_in_replacement_lines_not_interpreted(self):
        content = "<!-- BLOG:START -->\nold\n<!-- BLOG:END -->\n"
        result = replace_block(content, "BLOG", [r"- a \1 weird title"])
        self.assertIn(r"a \1 weird title", result)


class TestStarsBadgeLine(unittest.TestCase):
    def test_embeds_count_and_links_to_repos_sorted_by_stars(self):
        line = stars_badge_line(187)
        self.assertIn("total%20stars-187-yellow", line)
        self.assertIn("github.com/dcondrey?tab=repositories&sort=stargazers", line)

    def test_zero_is_valid(self):
        line = stars_badge_line(0)
        self.assertIn("total%20stars-0-yellow", line)


if __name__ == "__main__":
    unittest.main()
