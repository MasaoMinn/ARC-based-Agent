package com.example.springwebtlias.mapper;

import com.example.springwebtlias.pojo.Dept;
import org.apache.ibatis.annotations.*;

import java.util.List;

@Mapper
public interface DeptMapper {


    @Select("select * from dept")
    public List<Dept> list() ;


    @Delete("delete from dept where id = #{id} ;")
    void delete(int id) ;

    @Insert("insert into dept (name,create_time,update_time) values (#{name},#{createTime},#{updateTime});")
    void add(Dept dept);

    @Select("select * from dept where id = #{id}")
    Dept selectById(Integer id);

    @Update("update dept set name = #{name},update_time = #{updateTime}  where id = #{id} ;")
    void change(Dept dept);
}
