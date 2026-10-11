"""Only rendered card-side transitions delay readiness; backs remain masked."""
import pytest

from balatro_agent.policy import canonical


@pytest.mark.parametrize("area", ["hand", "jokers", "consumeables"])
@pytest.mark.parametrize("facing,sprite", [("front", "back"), ("back", "front")])
def test_visible_flip_delays_ready_until_rendered_side_matches(lua_reader, area, facing, sprite):
    lua, snapshot = lua_reader
    lua.execute(f"G.{area}.cards={{card('SECRET_TRANSITION')}}; G.{area}.cards[1].facing='{facing}'; G.{area}.cards[1].sprite_facing='{sprite}'")
    pending = snapshot()
    assert pending["ready"] is False and pending["ready_reason"] == "processing"
    assert "SECRET_TRANSITION" not in canonical(pending)
    lua.execute(f"G.{area}.cards[1].sprite_facing='{facing}'; G.{area}.cards[1].flipping='b2f'")
    completed = snapshot()
    assert completed["ready"] is True and completed["ready_reason"] == "ui_operable"
    if facing == "back":
        assert "SECRET_TRANSITION" not in canonical(completed)


@pytest.mark.parametrize("flag", ["b2f", "f2b"])
def test_persistent_native_flipping_flag_is_not_a_wait_condition(lua_reader, flag):
    lua, snapshot = lua_reader
    lua.execute(f"G.hand.cards[1].flipping='{flag}'")
    assert snapshot()["ready"] is True


def test_stable_back_card_is_actionable_but_never_revealed(lua_reader):
    lua, snapshot = lua_reader
    lua.execute("G.hand.cards[1].facing='back'; G.hand.cards[1].sprite_facing='back'; G.hand.cards[1].flipping='f2b'; G.hand.cards[1].public_name='SECRET_BACK'")
    result = snapshot()
    assert result["ready"] is True and "SECRET_BACK" not in canonical(result)
    hand = next(region for region in result["public"]["regions"] if region["name"] == "hand")
    assert hand["cards"][0] == {"position": 0, "selected": False, "visibility": "face_down"}


@pytest.mark.parametrize("scene", ["hidden_card", "deck", "unused_shop", "terminal"])
def test_undisplayed_or_irrelevant_animations_never_block_ready(lua_reader, scene):
    lua, snapshot = lua_reader
    if scene == "hidden_card":
        lua.execute("G.hand.cards[1].sprite_facing='back'; G.hand.cards[1].states.visible=false")
    elif scene == "deck":
        lua.execute("G.deck.cards[1].sprite_facing='back'")
    elif scene == "unused_shop":
        lua.execute("G.shop_jokers=area({card('SECRET_SHOP')}); G.shop_jokers.cards[1].sprite_facing='back'")
    else:
        lua.execute("G.STATE=G.STATES.GAME_OVER; G.OVERLAY_MENU=ui_box({}, {ui({id='game_over',text='GAME OVER'}),ui({button='go_to_menu'})}); G.hand.cards[1].sprite_facing='back'")
    result = snapshot()
    assert result["ready"] is True and "SECRET_SHOP" not in canonical(result)
