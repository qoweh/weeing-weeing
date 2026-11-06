import useProfilePhoto from "./useProfilePhoto";

/** 등록한 사진이 있으면 사진을, 없으면 이름 첫 글자를 원형으로 보여준다. */
export default function ProfileAvatar({
  user,
  size = 36,
}: {
  user: { name: string; employee_no: string };
  size?: number;
}) {
  const { photo } = useProfilePhoto(user.employee_no);
  return (
    <span
      className="profile-avatar"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}
      aria-hidden="true"
    >
      {photo ? <img src={photo} alt="" /> : user.name?.slice(0, 1)}
    </span>
  );
}
