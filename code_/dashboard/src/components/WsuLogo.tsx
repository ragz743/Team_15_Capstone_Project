import logo from "../assets/wsu-logo.png";

/** The WSU Cougar mark, same asset and sizing approach as the chat app's WsuLogo. */
export default function WsuLogo() {
  return <img className="wsu-logo" src={logo} alt="" draggable={false} />;
}
