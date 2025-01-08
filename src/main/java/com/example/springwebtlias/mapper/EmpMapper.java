package com.example.springwebtlias.mapper;

import com.example.springwebtlias.pojo.Emp;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.time.LocalDateTime;
import java.util.List;

@Mapper
public interface EmpMapper {

//    @Select("select count(*) from emp")
//    long getCount();
//
//    @Select("select * from emp limit #{start},#{pageSize}")
//    List<Emp> getList(Integer start, Integer pageSize);

    //@Select("select * from emp")
    List<Emp> getList(String name, Short gender, LocalDateTime begin,LocalDateTime end);

    void delete(List<Integer> ids);

   @Insert("insert into emp (username, name, gender, image, job, entrydate, dept_id, create_time, update_time) values (#{username},#{name},#{gender},#{image},#{job},#{entrydate},#{deptId},#{createTime},#{updateTime});")
    void save(Emp emp);
}
